"""
Retail Sentiment Intelligence — Alert Engine
Detects anomalies: volume spikes, sentiment crashes, emerging topics.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("alerts")

# Rules file (edited from the dashboard Alert Rules panel). Values here take
# precedence over the hard-coded defaults in this module. Kept next to the
# API so both write and read from the same place.
_RULES_PATH = Path("data/alert_rules.json")


def _load_rules() -> dict:
    """Load user-edited alert rules from disk. Missing/malformed → empty dict."""
    if not _RULES_PATH.exists():
        return {}
    try:
        return json.loads(_RULES_PATH.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("alert_rules_load_failed", error=str(e))
        return {}


class AlertEngine:
    """Detects anomalies and generates alerts."""

    def __init__(self, storage):
        self.storage = storage

    def detect_all(self) -> list[dict]:
        """Run all alert detectors and return triggered alerts. Honors the
        per-detector `enabled` flag and threshold overrides stored in
        data/alert_rules.json (edited via the dashboard).
        """
        rules = _load_rules()

        def _enabled(key: str) -> bool:
            r = rules.get(key)
            return True if not r else bool(r.get("enabled", True))

        def _val(key: str, field: str, default):
            r = rules.get(key) or {}
            v = r.get(field)
            return v if v is not None else default

        alerts = []
        if _enabled("volume_spike"):
            alerts.extend(self.detect_volume_spike(sigma_threshold=float(_val("volume_spike", "sigma_threshold", 2.0))))
        if _enabled("sentiment_crash"):
            alerts.extend(self.detect_sentiment_crash(drop_threshold=float(_val("sentiment_crash", "drop_threshold", 0.3))))
        if _enabled("emerging_topic"):
            alerts.extend(self.detect_emerging_topics(min_count=int(_val("emerging_topic", "min_posts", 5))))
        if _enabled("competitor_negative"):
            # This detector uses week-over-week deltas, not sigma. `sigma_threshold`
            # in the rules JSON exists for symmetry with the other rules; the
            # actual delta_threshold is left at its class-level default.
            alerts.extend(self.detect_competitor_neg_spike())
        return alerts

    def detect_volume_spike(self, sigma_threshold: float = 2.0) -> list[dict]:
        """
        Detect volume spikes: aspect mentions > 2σ above 7-day mean.
        """
        alerts = []
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y-%m-%d")

        # Get today's aggregate
        today_agg = self.storage.get_item("aggregates", f"agg_{today_key}_daily", today_key)
        if not today_agg:
            return []

        # Get last 7 days for baseline
        daily_counts = []
        for i in range(1, 8):
            past_date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            past_agg = self.storage.get_item("aggregates", f"agg_{past_date}_daily", past_date)
            if past_agg:
                daily_counts.append(past_agg.get("total_posts", 0))

        if len(daily_counts) < 3:
            return []  # Not enough history

        mean = sum(daily_counts) / len(daily_counts)
        std = math.sqrt(sum((x - mean) ** 2 for x in daily_counts) / len(daily_counts))

        if std == 0:
            return []

        today_count = today_agg.get("total_posts", 0)
        z_score = (today_count - mean) / std

        if z_score > sigma_threshold:
            alerts.append({
                "id": f"alert_spike_{today_key}",
                "type": "volume_spike",
                "severity": "high" if z_score > 3.0 else "medium",
                "title": f"Volume spike detected: {today_count} posts today ({z_score:.1f}σ above mean)",
                "details": {
                    "today_count": today_count,
                    "mean_7d": round(mean, 1),
                    "std_7d": round(std, 1),
                    "z_score": round(z_score, 2),
                },
                "detected_at": now.isoformat(),
                "time_window": today_key,
            })

        # Per-aspect spikes
        today_aspects = today_agg.get("aspect_breakdown", {})
        for aspect_name, stats in today_aspects.items():
            # Legacy aggregates store int counts; current ones store dicts.
            if isinstance(stats, dict):
                today_count = stats.get("count", 0)
            elif isinstance(stats, (int, float)):
                today_count = int(stats)
            else:
                continue

            aspect_history = self._get_aspect_history(aspect_name, 7)
            if len(aspect_history) < 3:
                continue

            aspect_mean = sum(aspect_history) / len(aspect_history)
            aspect_std = math.sqrt(sum((x - aspect_mean) ** 2 for x in aspect_history) / len(aspect_history))
            if aspect_std == 0:
                continue

            aspect_z = (today_count - aspect_mean) / aspect_std
            if aspect_z > sigma_threshold:
                alerts.append({
                    "id": f"alert_spike_{today_key}_{aspect_name}",
                    "type": "volume_spike",
                    "severity": "high" if aspect_z > 3.0 else "medium",
                    "title": f"'{aspect_name}' mentions spike: {today_count} today ({aspect_z:.1f}σ above mean)",
                    "details": {
                        "aspect": aspect_name,
                        "today_count": today_count,
                        "mean_7d": round(aspect_mean, 1),
                        "z_score": round(aspect_z, 2),
                    },
                    "detected_at": now.isoformat(),
                    "time_window": today_key,
                })

        return alerts

    def detect_sentiment_crash(self, drop_threshold: float = 0.3) -> list[dict]:
        """
        Detect sentiment crashes: drop > 0.3 in negative ratio vs yesterday.
        """
        alerts = []
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y-%m-%d")
        yesterday_key = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        today_agg = self.storage.get_item("aggregates", f"agg_{today_key}_daily", today_key)
        yesterday_agg = self.storage.get_item("aggregates", f"agg_{yesterday_key}_daily", yesterday_key)

        if not today_agg or not yesterday_agg:
            return []

        today_neg = today_agg.get("sentiment_distribution", {}).get("negative", 0)
        yesterday_neg = yesterday_agg.get("sentiment_distribution", {}).get("negative", 0)

        # If negative ratio increased by more than threshold
        neg_increase = today_neg - yesterday_neg
        if neg_increase > drop_threshold:
            alerts.append({
                "id": f"alert_crash_{today_key}",
                "type": "sentiment_crash",
                "severity": "critical" if neg_increase > 0.4 else "high",
                "title": f"Sentiment crash: negative ratio jumped +{neg_increase:.0%} vs yesterday",
                "details": {
                    "today_negative_ratio": round(today_neg, 3),
                    "yesterday_negative_ratio": round(yesterday_neg, 3),
                    "delta": round(neg_increase, 3),
                },
                "detected_at": now.isoformat(),
                "time_window": today_key,
            })

        return alerts

    def detect_emerging_topics(self, min_count: int = 5) -> list[dict]:
        """
        Detect emerging topics: new key phrases appearing ≥5 times today
        that weren't present yesterday.
        """
        alerts = []
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y-%m-%d")

        # Get today's analyses for key phrases
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        query = "SELECT data FROM analyses WHERE json_extract(data, '$.analyzed_at') >= ? AND json_extract(data, '$.analyzed_at') < ?"
        today_analyses = self.storage.query("analyses", query, [start.isoformat(), end.isoformat()])

        if not today_analyses:
            return []

        # Count key phrases
        phrase_counts = defaultdict(int)
        for analysis in today_analyses:
            for phrase in analysis.get("key_phrases", []):
                phrase_counts[phrase.lower()] += 1

        # Find phrases exceeding threshold
        emerging = [(phrase, count) for phrase, count in phrase_counts.items() if count >= min_count]
        emerging.sort(key=lambda x: x[1], reverse=True)

        for phrase, count in emerging[:3]:  # Top 3 emerging topics
            alerts.append({
                "id": f"alert_topic_{today_key}_{phrase[:20]}",
                "type": "emerging_topic",
                "severity": "medium",
                "title": f"Emerging topic: '{phrase}' ({count} mentions today)",
                "details": {
                    "phrase": phrase,
                    "count": count,
                },
                "detected_at": now.isoformat(),
                "time_window": today_key,
            })

        return alerts

    def _get_aspect_history(self, aspect_name: str, days: int) -> list[int]:
        """Get daily counts for an aspect over the last N days."""
        now = datetime.now(timezone.utc)
        counts = []
        for i in range(1, days + 1):
            past_date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            past_agg = self.storage.get_item("aggregates", f"agg_{past_date}_daily", past_date)
            if past_agg:
                aspects = past_agg.get("aspect_breakdown", {})
                entry = aspects.get(aspect_name)
                if isinstance(entry, dict):
                    counts.append(entry.get("count", 0))
                elif isinstance(entry, (int, float)):
                    counts.append(int(entry))
                else:
                    counts.append(0)
        return counts

    def detect_competitor_neg_spike(
        self,
        min_posts_per_window: int = 25,
        delta_threshold: float = 0.15,
    ) -> list[dict]:
        """Per-competitor week-over-week negative-ratio spike.

        For each competitor subreddit, compare its negative ratio in the last
        7 days vs the previous 7 days. Emit a medium-severity alert if the
        ratio jumped by `delta_threshold` (e.g. +15 pts) and there are enough
        posts in both windows to be meaningful.
        """
        from src.utils.segments import macro_segment_for

        now = datetime.now(timezone.utc)
        this_start = now - timedelta(days=7)
        prev_start = now - timedelta(days=14)

        sql = (
            "SELECT a.data AS adata, r.subreddit AS sub, r.created_timestamp AS ts "
            "FROM analyses a JOIN raw_posts r ON a.post_id = r.id "
            "WHERE r.created_timestamp >= ?"
        )
        try:
            cur = self.storage._conn.execute(sql, (prev_start.timestamp(),))
            rows = cur.fetchall()
        except Exception:
            return []

        import json as _json
        bucket: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: {"this": {"neg": 0, "total": 0}, "prev": {"neg": 0, "total": 0}}
        )
        for row in rows:
            sub = row["sub"]
            if not sub or macro_segment_for(sub) != "competitor":
                continue
            ts = row["ts"] or 0
            window = "this" if ts >= this_start.timestamp() else "prev"
            try:
                a = _json.loads(row["adata"])
            except Exception:
                continue
            bucket[sub][window]["total"] += 1
            if a.get("sentiment") == "negative":
                bucket[sub][window]["neg"] += 1

        alerts = []
        for sub, b in bucket.items():
            t_total = b["this"]["total"]
            p_total = b["prev"]["total"]
            if t_total < min_posts_per_window or p_total < min_posts_per_window:
                continue
            t_ratio = b["this"]["neg"] / t_total
            p_ratio = b["prev"]["neg"] / p_total
            delta = t_ratio - p_ratio
            if delta < delta_threshold:
                continue
            alerts.append({
                "id": f"alert_comp_neg_{sub}_{now.strftime('%Y%m%d')}",
                "type": "competitor_neg_spike",
                "severity": "high" if delta >= 0.25 else "medium",
                "title": f"r/{sub} negative ratio jumped +{delta:.0%} WoW",
                "details": {
                    "subreddit": sub,
                    "this_week_negative_ratio": round(t_ratio, 3),
                    "prev_week_negative_ratio": round(p_ratio, 3),
                    "delta": round(delta, 3),
                    "this_week_posts": t_total,
                    "prev_week_posts": p_total,
                },
                "detected_at": now.isoformat(),
                "time_window": now.strftime("%Y-%m-%d"),
            })
        return alerts
