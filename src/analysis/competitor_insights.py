"""Competitor insights — analyse competitor subreddit chatter to surface
pain points and 'what Walmart can learn' recommendations.

Deterministic by design: no LLM call. We pull analysed rows from the
`analyses` table for the competitor macro-segment over the requested window,
roll up by aspect + subreddit, and emit:

- `pain_points`: top competitor aspects with the worst negative ratio
- `walmart_comparison`: same aspects scored against Walmart's own segment
- `recommendations`: ordered list with priority levels (high/medium/low)
- `top_subreddits`: most-active competitor communities in window
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.storage.store import SQLiteBackend
from src.utils.logger import get_logger
from src.utils.segments import macro_segment_for

log = get_logger("competitor_insights")

MIN_POSTS_FOR_ASPECT = 8         # ignore aspects with too little signal
DEFAULT_WINDOW_DAYS = 7
HIGH_PRIO_RATIO = 0.60           # >=60% negative on the aspect
MEDIUM_PRIO_RATIO = 0.40


def _load_analyses(storage: SQLiteBackend, since_iso: str) -> list[dict]:
    """Pull analysis rows created (best-effort: by created_at on the source
    post) after `since_iso`. We join on raw_posts to filter by timestamp.
    """
    sql = (
        "SELECT a.data AS adata, r.data AS rdata "
        "FROM analyses a JOIN raw_posts r ON a.post_id = r.id "
        "WHERE r.created_timestamp >= ?"
    )
    since_ts = datetime.fromisoformat(since_iso.replace("Z", "+00:00")).timestamp()
    cur = storage._conn.execute(sql, (since_ts,))
    rows: list[dict] = []
    for row in cur.fetchall():
        try:
            a = json.loads(row["adata"])
            r = json.loads(row["rdata"])
            a["_raw_subreddit"] = r.get("subreddit", a.get("subreddit", ""))
            a["_raw_text"] = r.get("text") or r.get("title", "")
            rows.append(a)
        except Exception:  # noqa: BLE001
            continue
    return rows


def _bucket(analyses: list[dict]) -> dict:
    """Bucket analyses by macro_segment → aspect → counters."""
    buckets: dict = {
        "walmart":    defaultdict(lambda: {"pos": 0, "neg": 0, "neu": 0, "total": 0, "examples": []}),
        "competitor": defaultdict(lambda: {"pos": 0, "neg": 0, "neu": 0, "total": 0, "examples": []}),
    }
    subreddit_counts: dict[str, Counter] = defaultdict(Counter)

    for a in analyses:
        sub = a.get("_raw_subreddit") or a.get("subreddit") or ""
        macro = macro_segment_for(sub) if sub else "competitor"
        if macro not in buckets:
            continue
        sentiment = a.get("sentiment", "neutral")
        for aspect_raw in (a.get("aspects") or []):
            # Aspects may be plain strings or {name, sentiment, ...} dicts.
            if isinstance(aspect_raw, dict):
                aspect = aspect_raw.get("name") or aspect_raw.get("aspect")
            else:
                aspect = aspect_raw
            if not aspect or not isinstance(aspect, str):
                continue
            slot = buckets[macro][aspect]
            slot["total"] += 1
            if sentiment == "positive":
                slot["pos"] += 1
            elif sentiment == "negative":
                slot["neg"] += 1
                if len(slot["examples"]) < 3:
                    text = (a.get("_raw_text") or "")[:200]
                    slot["examples"].append({
                        "subreddit": sub,
                        "excerpt": text,
                    })
            else:
                slot["neu"] += 1
        subreddit_counts[macro][sub] += 1

    return {"buckets": buckets, "sub_counts": subreddit_counts}


def _pain_points(competitor_bucket: dict) -> list[dict]:
    """Return aspects sorted by competitor negative ratio (desc)."""
    out = []
    for aspect, c in competitor_bucket.items():
        total = c["total"]
        if total < MIN_POSTS_FOR_ASPECT:
            continue
        neg_ratio = c["neg"] / total if total else 0.0
        out.append({
            "aspect": aspect,
            "total": total,
            "negative": c["neg"],
            "positive": c["pos"],
            "neutral": c["neu"],
            "negative_ratio": round(neg_ratio, 3),
            "examples": c["examples"],
        })
    out.sort(key=lambda x: (-x["negative_ratio"], -x["total"]))
    return out[:10]


def _walmart_comparison(pain_points: list[dict], walmart_bucket: dict) -> list[dict]:
    """For each competitor pain point, report Walmart's own negative ratio."""
    out = []
    for pp in pain_points:
        aspect = pp["aspect"]
        wmt = walmart_bucket.get(aspect, {"total": 0, "neg": 0, "pos": 0})
        wmt_total = wmt.get("total", 0)
        wmt_ratio = (wmt["neg"] / wmt_total) if wmt_total else 0.0
        delta = pp["negative_ratio"] - wmt_ratio
        out.append({
            "aspect": aspect,
            "competitor_negative_ratio": pp["negative_ratio"],
            "walmart_negative_ratio": round(wmt_ratio, 3),
            "walmart_total": wmt_total,
            "delta": round(delta, 3),
        })
    return out


def _recommendations(pain_points: list[dict], comparison: list[dict]) -> list[dict]:
    """Turn pain points into priority-tagged recommendations."""
    comp_by_aspect = {c["aspect"]: c for c in comparison}
    out = []
    for pp in pain_points:
        ratio = pp["negative_ratio"]
        priority = "low"
        if ratio >= HIGH_PRIO_RATIO:
            priority = "high"
        elif ratio >= MEDIUM_PRIO_RATIO:
            priority = "medium"

        cmp = comp_by_aspect.get(pp["aspect"], {})
        delta = cmp.get("delta", 0.0)
        wmt_negr = cmp.get("walmart_negative_ratio", 0.0)

        if delta > 0.05:
            angle = (
                f"Competitors are struggling with {pp['aspect']} "
                f"({ratio:.0%} negative) much more than Walmart ({wmt_negr:.0%}). "
                "Lean into this as a competitive marketing angle."
            )
        elif delta < -0.05:
            angle = (
                f"Walmart is doing worse on {pp['aspect']} ({wmt_negr:.0%} negative) "
                f"than competitors ({ratio:.0%}). Investigate root causes."
            )
        else:
            angle = (
                f"Both Walmart and competitors trend negative on {pp['aspect']} "
                f"(~{ratio:.0%}). Industry-wide friction — opportunity to differentiate."
            )

        out.append({
            "aspect": pp["aspect"],
            "priority": priority,
            "headline": angle,
            "supporting_count": pp["total"],
            "competitor_negative_ratio": pp["negative_ratio"],
            "walmart_negative_ratio": wmt_negr,
        })
    return out


def generate_insights(
    storage: SQLiteBackend,
    window_days: int = DEFAULT_WINDOW_DAYS,
    kind: str = "competitor_on_demand",
) -> dict:
    """Build a competitor-insights payload and persist it."""
    window_days = max(1, min(int(window_days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    since_iso = since.isoformat()
    analyses = _load_analyses(storage, since_iso)
    bundle = _bucket(analyses)

    competitor_bucket = bundle["buckets"]["competitor"]
    walmart_bucket = bundle["buckets"]["walmart"]
    pain = _pain_points(competitor_bucket)
    comparison = _walmart_comparison(pain, walmart_bucket)
    recs = _recommendations(pain, comparison)

    top_subs = bundle["sub_counts"]["competitor"].most_common(8)
    top_subs_list = [{"subreddit": s, "post_count": n} for s, n in top_subs]

    payload = {
        "window_days": window_days,
        "since": since_iso,
        "analyses_count": len(analyses),
        "pain_points": pain,
        "walmart_comparison": comparison,
        "recommendations": recs,
        "top_competitor_subreddits": top_subs_list,
    }

    generated_at = datetime.now(timezone.utc).isoformat()
    insight_id = storage.insights_upsert(kind, window_days, payload, generated_at)
    log.info(
        "competitor_insights_generated",
        id=insight_id,
        kind=kind,
        window_days=window_days,
        analyses=len(analyses),
        pain_points=len(pain),
    )
    return {"id": insight_id, "kind": kind, "generated_at": generated_at, "payload": payload}


def generate_daily_insights(storage: SQLiteBackend) -> dict:
    """Scheduler entry point — runs the 7-day rollup, tagged `competitor_daily`."""
    return generate_insights(storage, window_days=DEFAULT_WINDOW_DAYS, kind="competitor_daily")
