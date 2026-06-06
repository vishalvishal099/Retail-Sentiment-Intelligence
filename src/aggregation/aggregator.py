"""
Retail Sentiment Intelligence — Aggregation Engine
Computes hourly/daily/weekly rollups of sentiment and aspects.
Groups by time window + aspect, computes distribution stats.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("aggregator")


class Aggregator:
    """Computes time-window aggregates from analysis records."""

    def __init__(self, storage):
        self.storage = storage

    def aggregate_window(self, window_type: str = "daily", target_date: Optional[datetime] = None) -> dict:
        """
        Compute aggregates for a given time window.
        window_type: "hourly" | "daily" | "weekly"
        """
        now = target_date or datetime.now(timezone.utc)

        if window_type == "hourly":
            window_start = now.replace(minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(hours=1)
            window_key = window_start.strftime("%Y-%m-%dT%H:00")
        elif window_type == "daily":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(days=1)
            window_key = window_start.strftime("%Y-%m-%d")
        elif window_type == "weekly":
            # Start of week (Monday)
            days_since_monday = now.weekday()
            window_start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(weeks=1)
            window_key = f"{window_start.strftime('%Y-%m-%d')}_week"
        else:
            raise ValueError(f"Unknown window_type: {window_type}")

        # Fetch analyses in this window
        analyses = self._fetch_analyses_in_window(window_start, window_end)

        if not analyses:
            return {}

        # Compute aggregate
        aggregate = self._compute_aggregate(analyses, window_key, window_type)

        # Store aggregate
        self.storage.upsert("aggregates", aggregate)
        log.info("aggregate_computed", window=window_key, type=window_type, posts=aggregate["total_posts"])

        return aggregate

    def _fetch_analyses_in_window(self, start: datetime, end: datetime) -> list[dict]:
        """Fetch all analyses within a time window."""
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        # SQLite query
        query = "SELECT data FROM analyses WHERE json_extract(data, '$.analyzed_at') >= ? AND json_extract(data, '$.analyzed_at') < ?"
        return self.storage.query("analyses", query, [start_iso, end_iso])

    def _compute_aggregate(self, analyses: list[dict], window_key: str, window_type: str) -> dict:
        """Compute statistics from a list of analyses."""
        total = len(analyses)
        sentiment_counts = defaultdict(int)
        aspect_stats = defaultdict(lambda: {"count": 0, "positive": 0, "negative": 0, "neutral": 0})
        subreddit_counts = defaultdict(int)
        trusted_count = 0
        needs_review_count = 0

        for analysis in analyses:
            # Sentiment distribution
            sentiment = analysis.get("sentiment", "neutral")
            sentiment_counts[sentiment] += 1

            # Trust tracking
            trust_score = analysis.get("trust_score")
            if trust_score is not None and trust_score >= 0.5:
                trusted_count += 1

            # Review queue
            if analysis.get("needs_review"):
                needs_review_count += 1

            # Aspect breakdown
            aspects = analysis.get("aspects", [])
            for asp in aspects:
                if isinstance(asp, str):
                    aspect_name = asp
                    asp_sentiment = analysis.get("sentiment", "neutral")
                elif isinstance(asp, dict):
                    aspect_name = asp.get("aspect", "unknown")
                    asp_sentiment = asp.get("sentiment", analysis.get("sentiment", "neutral"))
                else:
                    continue
                aspect_stats[aspect_name]["count"] += 1
                aspect_stats[aspect_name][asp_sentiment] += 1

            # Subreddit distribution
            subreddit = analysis.get("subreddit", "unknown")
            subreddit_counts[subreddit] += 1

        # Build aggregate record
        return {
            "id": f"agg_{window_key}_{window_type}",
            "time_window": window_key,
            "window_type": window_type,
            "total_posts": total,
            "trusted_posts": trusted_count,
            "needs_review": needs_review_count,
            "sentiment_distribution": {
                "positive": sentiment_counts.get("positive", 0) / max(total, 1),
                "negative": sentiment_counts.get("negative", 0) / max(total, 1),
                "neutral": sentiment_counts.get("neutral", 0) / max(total, 1),
            },
            "sentiment_counts": dict(sentiment_counts),
            "aspect_breakdown": {
                name: {
                    "count": stats["count"],
                    "positive_ratio": stats["positive"] / max(stats["count"], 1),
                    "negative_ratio": stats["negative"] / max(stats["count"], 1),
                    "neutral_ratio": stats["neutral"] / max(stats["count"], 1),
                }
                for name, stats in aspect_stats.items()
            },
            "subreddit_distribution": dict(subreddit_counts),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "partition_key": window_key,
        }

    def compute_trend(self, aspect: Optional[str] = None, days: int = 7) -> list[dict]:
        """Compute daily sentiment trend for the last N days."""
        now = datetime.now(timezone.utc)
        trend = []

        for i in range(days, 0, -1):
            target = now - timedelta(days=i)
            window_key = target.strftime("%Y-%m-%d")
            agg_id = f"agg_{window_key}_daily"

            existing = self.storage.get_item("aggregates", agg_id, window_key)
            if existing:
                point = {
                    "date": window_key,
                    "total_posts": existing.get("total_posts", 0),
                    "sentiment_distribution": existing.get("sentiment_distribution", {}),
                }
                if aspect and aspect in existing.get("aspect_breakdown", {}):
                    point["aspect_data"] = existing["aspect_breakdown"][aspect]
                trend.append(point)

        return trend

    def get_top_issues(self, window_key: str) -> list[dict]:
        """Get top issues from an aggregate (most negative aspects by volume)."""
        agg = self.storage.get_item("aggregates", f"agg_{window_key}_daily", window_key)
        if not agg:
            return []

        aspects = agg.get("aspect_breakdown", {})
        issues = []
        for name, stats in aspects.items():
            # Handle both formats: dict with count/negative_ratio, or plain int count
            if isinstance(stats, dict):
                count = stats.get("count", 0)
                neg_ratio = stats.get("negative_ratio", 0)
            else:
                count = int(stats) if stats else 0
                neg_ratio = 0.3  # default estimate when ratio unavailable
            score = count * neg_ratio
            issues.append({
                "aspect": name,
                "count": count,
                "negative_ratio": neg_ratio,
                "severity_score": round(score, 2),
            })

        issues.sort(key=lambda x: x["severity_score"], reverse=True)
        return issues[:5]
