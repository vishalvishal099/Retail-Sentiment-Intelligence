"""
Retail Sentiment Intelligence — Combined Trust Scorer
Combines metadata, dedup, and LLM credibility into a single trust score.
Formula: 0.4 * metadata + 0.3 * dedup + 0.3 * llm
"""

from typing import Optional

from src.trust.heuristics import score_metadata
from src.trust.dedup import score_originality
from src.analysis.llm_client import BaseLLMClient
from src.utils.config import TrustConfig
from src.utils.logger import get_logger

log = get_logger("trust_scorer")


class TrustScorer:
    """
    Combined trust scorer.
    Low-trust units are FLAGGED, not dropped (per R5).
    """

    def __init__(self, config: TrustConfig, llm_client: Optional[BaseLLMClient] = None):
        self.config = config
        self.llm_client = llm_client

    def score(self, unit: dict) -> dict:
        """
        Compute trust score for a post/comment.
        Returns the unit dict with trust_score and trust_flags added.
        """
        # Component scores
        meta_score = score_metadata(unit, self.config)
        dedup_score = score_originality(unit)

        # LLM credibility — only invoked when metadata is ambiguous
        # (0.3 < meta < 0.8). Outside that band metadata is already
        # decisive, so we skip the call to cap cost on cloud providers.
        # With the HF provider this routes to a rule-based heuristic
        # (free); with cloud providers it is a real LLM call.
        llm_score = 0.5  # neutral default
        llm_flags: list[str] = []
        if self.llm_client and 0.3 < meta_score < 0.8:
            cred_result = self.llm_client.check_credibility(
                text=self._get_text(unit),
                metadata=unit.get("author_metadata", {}),
            )
            llm_score = cred_result.get("credibility_score", 0.5)
            llm_flags = cred_result.get("flags", [])

        # Weighted combination
        combined = (
            self.config.weight_metadata * meta_score +
            self.config.weight_dedup * dedup_score +
            self.config.weight_llm * llm_score
        )
        combined = round(min(max(combined, 0.0), 1.0), 3)

        # Determine trust status (flag, not drop)
        is_trusted = combined >= self.config.threshold

        # Augment unit
        unit["trust_score"] = combined
        unit["trust_components"] = {
            "metadata": meta_score,
            "dedup": dedup_score,
            "llm": llm_score,
        }
        unit["trust_flags"] = llm_flags
        unit["is_trusted"] = is_trusted

        if not is_trusted:
            unit["processing_status"] = "flagged_low_trust"
            log.info("low_trust_flagged", unit_id=unit.get("id"), score=combined)

        return unit

    def score_batch(self, units: list[dict]) -> list[dict]:
        """Score a batch of units."""
        scored = []
        for unit in units:
            scored.append(self.score(unit))
        log.info("trust_batch_scored", count=len(scored),
                 trusted=sum(1 for u in scored if u.get("is_trusted")))
        return scored

    def _get_text(self, unit: dict) -> str:
        title = unit.get("title", "") or ""
        body = unit.get("body", "") or ""
        return f"{title} {body}".strip()
