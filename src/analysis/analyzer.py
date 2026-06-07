"""
Retail Sentiment Intelligence — Analyzer
Orchestrates sentiment + aspect analysis on batches of posts/comments.
Model-agnostic: uses whatever LLM client is configured.
"""

from datetime import datetime, timezone
from typing import Optional

from src.analysis.llm_client import BaseLLMClient
from src.utils.config import AnalysisConfig
from src.utils.logger import get_logger

log = get_logger("analyzer")


class SentimentAnalyzer:
    """Orchestrates analysis on posts/comments using the configured LLM."""

    def __init__(self, llm_client: BaseLLMClient, config: AnalysisConfig):
        self.llm = llm_client
        self.config = config

    def analyze_unit(self, unit: dict) -> dict:
        """Analyze a single post or comment."""
        text = self._get_text(unit)
        result = self.llm.analyze_sentiment(text)

        return self._build_analysis_record(unit, result)

    def analyze_batch(self, units: list[dict]) -> list[dict]:
        """Analyze a batch of posts/comments."""
        texts = [self._get_text(u) for u in units]
        results = self.llm.analyze_batch(texts)

        analyses = []
        for unit, result in zip(units, results):
            analyses.append(self._build_analysis_record(unit, result))

        log.info("batch_analyzed", count=len(analyses),
                 model=self.llm.model_name)
        return analyses

    def _get_text(self, unit: dict) -> str:
        """Extract text from a post or comment for analysis.

        Vision branch: if upstream pipeline stages have populated
        `unit["image_caption"]` (Gemma 3 4B output), we append it as
        `[image: ...]` so the downstream sentiment + aspect models see it
        as part of the post body. This is what makes image-only posts
        analyzable end-to-end without changing those models.
        """
        title = unit.get("title", "") or ""
        body = unit.get("body", "") or ""
        subreddit = unit.get("subreddit", "unknown")
        unit_type = unit.get("unit_type", "post")
        caption = (unit.get("image_caption") or "").strip()
        cap_suffix = f" [image: {caption}]" if caption else ""

        if unit_type == "comment":
            return f"Comment from r/{subreddit}: \"{body}\""
        else:
            if title and body:
                return f"Post from r/{subreddit}: \"{title}\" — {body}{cap_suffix}"
            elif title:
                return f"Post from r/{subreddit}: \"{title}\"{cap_suffix}"
            elif body:
                return f"Post from r/{subreddit}: \"{body}\"{cap_suffix}"
            else:
                # Image-only post: caption IS the content.
                return f"Post from r/{subreddit}: \"{caption}\"" if caption else f"Post from r/{subreddit}: \"\""

    def _build_analysis_record(self, unit: dict, result: dict) -> dict:
        """Build the analysis record for storage."""
        unit_id = unit.get("id", "")
        confidence = result.get("sentiment_confidence", 0.0)

        return {
            "id": f"analysis_{unit_id}",
            "post_id": unit_id,
            "subreddit": unit.get("subreddit", ""),
            "unit_type": unit.get("unit_type", "post"),
            "trust_score": unit.get("trust_score"),
            "sentiment": result.get("sentiment", "neutral"),
            "sentiment_confidence": confidence,
            "aspects": result.get("aspects", []),
            "key_phrases": result.get("key_phrases", []),
            "summary": result.get("summary", ""),
            "model_used": result.get("model_used", self.llm.model_name),
            "model_version": result.get("model_version", self.llm.model_version),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "needs_review": confidence < self.config.confidence_threshold,
            "partition_key": unit.get("subreddit", ""),
        }
