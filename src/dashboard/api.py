"""
Retail Sentiment Intelligence — Dashboard API
FastAPI backend with REST endpoints + WebSocket for real-time alerts.

Pages served:
  P0: Brand Health, Aspect Drilldown, Review & Validate
  P1: Alert Feed, Post Explorer
  P2: Trust Analytics, Competitor Pulse, Copilot Chat
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.storage.store import create_storage
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine

range_builtin = range  # alias to avoid conflict with 'range' query parameter

log = get_logger("dashboard_api")

# Global state
_storage = None
_aggregator = None
_alert_engine = None
_config = None
_ws_connections: list[WebSocket] = []

# Pipeline runner state — single in-memory record. Concurrent runs are blocked.
_pipeline_state: dict = {
    "running": False,
    "last_run_id": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_status": None,  # "success" | "failed" | None
    "last_exit_code": None,
    "last_trigger": None,  # "manual" | "scheduled"
    "last_log_tail": [],
}
_pipeline_lock = asyncio.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PIPELINE_INTERVAL_MINUTES = int(os.environ.get("PIPELINE_INTERVAL_MINUTES", "60"))
_scheduler_task: asyncio.Task | None = None
_scheduler_started_at: datetime | None = None
_next_scheduled_run_at: datetime | None = None


async def _run_pipeline_subprocess(trigger: str) -> dict:
    """Run one pipeline cycle as a detached subprocess and update state.

    Uses the same Python interpreter the API is running under so we inherit the
    correct virtual environment. Captures stdout/stderr tail for the UI.
    """
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running", "state": _pipeline_state}

    async with _pipeline_lock:
        if _pipeline_state["running"]:
            return {"started": False, "reason": "already_running", "state": _pipeline_state}
        run_id = uuid.uuid4().hex[:12]
        _pipeline_state.update(
            running=True,
            last_run_id=run_id,
            last_started_at=datetime.now(timezone.utc).isoformat(),
            last_finished_at=None,
            last_status=None,
            last_exit_code=None,
            last_trigger=trigger,
        )
        log.info("pipeline_run_started", run_id=run_id, trigger=trigger)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_PROJECT_ROOT)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "src.pipeline",
        "--once",
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout_bytes, _ = await proc.communicate()
    output = (stdout_bytes or b"").decode(errors="replace")
    tail = output.strip().splitlines()[-25:]
    status = "success" if proc.returncode == 0 else "failed"
    _pipeline_state.update(
        running=False,
        last_finished_at=datetime.now(timezone.utc).isoformat(),
        last_status=status,
        last_exit_code=proc.returncode,
        last_log_tail=tail,
    )
    log.info("pipeline_run_finished", run_id=run_id, status=status, code=proc.returncode)
    return {"started": True, "run_id": run_id, "state": _pipeline_state}


async def _scheduler_loop():
    """Run the pipeline every `_PIPELINE_INTERVAL_MINUTES` while the API is up."""
    global _next_scheduled_run_at
    log.info("scheduler_loop_started", interval_minutes=_PIPELINE_INTERVAL_MINUTES)
    try:
        while True:
            _next_scheduled_run_at = datetime.now(timezone.utc) + timedelta(minutes=_PIPELINE_INTERVAL_MINUTES)
            await asyncio.sleep(_PIPELINE_INTERVAL_MINUTES * 60)
            try:
                await _run_pipeline_subprocess("scheduled")
            except Exception as e:  # noqa: BLE001
                log.error("scheduler_run_failed", error=str(e))
    except asyncio.CancelledError:
        log.info("scheduler_loop_stopped")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize storage and components on startup."""
    global _storage, _aggregator, _alert_engine, _config, _scheduler_task, _scheduler_started_at, _next_scheduled_run_at
    setup_logging()
    _config = load_config()
    _storage = create_storage(_config.storage)
    _aggregator = Aggregator(_storage)
    _alert_engine = AlertEngine(_storage)
    log.info("dashboard_api_started", port=_config.dashboard.port)
    if os.environ.get("PIPELINE_SCHEDULER", "on").lower() != "off":
        _scheduler_started_at = datetime.now(timezone.utc)
        _next_scheduled_run_at = _scheduler_started_at + timedelta(minutes=_PIPELINE_INTERVAL_MINUTES)
        _scheduler_task = asyncio.create_task(_scheduler_loop())
    yield
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    log.info("dashboard_api_shutdown")


def _ensure_initialized():
    """Lazily initialize if lifespan hasn't run (e.g., in TestClient)."""
    global _storage, _aggregator, _alert_engine, _config
    if _storage is None:
        _config = load_config()
        _storage = create_storage(_config.storage)
        _aggregator = Aggregator(_storage)
        _alert_engine = AlertEngine(_storage)


app = FastAPI(
    title="Retail Sentiment Intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (allow React frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ─── Pipeline control ─────────────────────────────────────────────────────────

@app.get("/api/pipeline/status")
def pipeline_status():
    """Current pipeline runner state."""
    next_run = _next_scheduled_run_at
    # Recompute next run from last finish if it's already in the past (the loop
    # advances it before the sleep, so we keep it monotonic for the UI).
    if next_run is not None and next_run < datetime.now(timezone.utc) and _pipeline_state["last_finished_at"]:
        try:
            last_fin = datetime.fromisoformat(_pipeline_state["last_finished_at"])
            next_run = last_fin + timedelta(minutes=_PIPELINE_INTERVAL_MINUTES)
        except ValueError:
            pass
    return {
        **_pipeline_state,
        "interval_minutes": _PIPELINE_INTERVAL_MINUTES,
        "scheduler_enabled": _scheduler_task is not None and not _scheduler_task.done(),
        "scheduler_started_at": _scheduler_started_at.isoformat() if _scheduler_started_at else None,
        "next_scheduled_run_at": next_run.isoformat() if next_run else None,
    }


@app.post("/api/pipeline/run")
async def pipeline_run(background_tasks: BackgroundTasks):
    """Trigger an immediate pipeline cycle. Returns 409-style payload if already running."""
    if _pipeline_state["running"]:
        return {
            "started": False,
            "reason": "already_running",
            "state": _pipeline_state,
        }
    background_tasks.add_task(_run_pipeline_subprocess, "manual")
    return {"started": True, "state": _pipeline_state}


# ─── P0: Brand Health Overview ─────────────────────────────────────────────────

# All brand-health windows now filter by the post's *creation* timestamp
# (raw_posts.created_timestamp), not by when our pipeline analyzed it. This makes
# "Last 24h" / "Today" / "Last 30 Days" consistent with the Post Explorer and
# with what an analyst expects to see for that calendar window.
_HOUR_RANGES = {"1h": 1, "2h": 2, "3h": 3, "6h": 6, "12h": 12, "24h": 24}
_DAY_RANGES = {
    "today": (0, 1),
    "yesterday": (1, 1),
    "week": (6, 7),
    "month": (29, 30),
    "60d": (59, 60),
    "90d": (89, 90),
}
_VALID_RANGES = list(_HOUR_RANGES.keys()) + list(_DAY_RANGES.keys())


def _resolve_window(range_token: str) -> tuple[datetime, datetime, int, str]:
    """Return (window_start, window_end, days_requested, date_label) for a range token.

    Day-based ranges with `days_back == 1` resolve to a single calendar day
    `offset_days` ago (today, yesterday). Multi-day ranges are rolling windows
    that end at *now* and span `days_back` calendar days backwards from today.
    """
    now = datetime.now(timezone.utc)
    if range_token in _HOUR_RANGES:
        hours = _HOUR_RANGES[range_token]
        win_start = now - timedelta(hours=hours)
        return (
            win_start,
            now,
            max(1, (hours + 23) // 24),
            f"{win_start.strftime('%H:%M')} → {now.strftime('%H:%M')} UTC",
        )
    offset_days, days_back = _DAY_RANGES[range_token]
    if days_back == 1:
        target = now - timedelta(days=offset_days)
        win_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        win_end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = target.strftime("%Y-%m-%d")
    else:
        # Rolling window ending at the current moment.
        win_end = now
        win_start = (now - timedelta(days=days_back - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"{win_start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}"
    return win_start, win_end, days_back, label


def _fetch_window_rows(start: datetime, end: datetime, extra_where: str = "", extra_params: list | None = None) -> list:
    """Return raw sqlite rows joining analyses with raw_posts by post creation time."""
    sql = (
        "SELECT a.data AS adata, r.data AS rdata "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ? "
    )
    params: list = [start.timestamp(), end.timestamp()]
    if extra_where:
        sql += f"  AND {extra_where} "
        params.extend(extra_params or [])
    return _storage._conn.execute(sql, params).fetchall()


def _compute_window_aggregate(start: datetime, end: datetime) -> dict:
    """Totals + sentiment + aspects + subreddits for posts CREATED in [start, end)."""
    import json as _json
    rows = _fetch_window_rows(start, end)
    sentiment_dist: Counter = Counter()
    aspect_counts: Counter = Counter()
    aspect_sentiment: dict[str, Counter] = {}
    subreddit_dist: Counter = Counter()
    trusted = 0
    for row in rows:
        a = _json.loads(row["adata"])
        sentiment = a.get("sentiment", "neutral")
        sentiment_dist[sentiment] += 1
        ts = a.get("trust_score")
        if ts is not None and ts >= 0.5:
            trusted += 1
        sub = a.get("subreddit", "")
        if sub:
            subreddit_dist[sub] += 1
        for asp in a.get("aspects", []) or []:
            name = asp if isinstance(asp, str) else (asp.get("aspect") if isinstance(asp, dict) else None)
            if not name:
                continue
            aspect_counts[name] += 1
            aspect_sentiment.setdefault(name, Counter())[sentiment] += 1
    return {
        "total_posts": len(rows),
        "trusted_posts": trusted,
        "sentiment_distribution": {
            "positive": sentiment_dist.get("positive", 0),
            "negative": sentiment_dist.get("negative", 0),
            "neutral": sentiment_dist.get("neutral", 0),
        },
        "aspect_breakdown": dict(aspect_counts),
        "aspect_sentiment": {k: dict(v) for k, v in aspect_sentiment.items()},
        "subreddit_distribution": dict(subreddit_dist),
    }


def _compute_trend_by_post_date(days: int) -> list[dict]:
    """Daily post-volume trend bucketed by post creation date (UTC day)."""
    import json as _json
    now = datetime.now(timezone.utc)
    base_start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    sql = (
        "SELECT a.data AS adata, "
        "       CAST(json_extract(r.data, '$.created_timestamp') AS REAL) AS cts "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ?"
    )
    rows = _storage._conn.execute(sql, [base_start.timestamp(), now.timestamp()]).fetchall()
    by_date: dict[str, Counter] = {}
    for row in rows:
        d = datetime.fromtimestamp(row["cts"], tz=timezone.utc).strftime("%Y-%m-%d")
        a = _json.loads(row["adata"])
        b = by_date.setdefault(d, Counter())
        b["total_posts"] += 1
        b[a.get("sentiment", "neutral")] += 1
    trend = []
    for i in range_builtin(days, 0, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        bucket = by_date.get(d, Counter())
        trend.append({
            "date": d,
            "total_posts": bucket.get("total_posts", 0),
            "sentiment_distribution": {
                "positive": bucket.get("positive", 0),
                "negative": bucket.get("negative", 0),
                "neutral": bucket.get("neutral", 0),
            },
        })
    return trend


def _compute_trend_by_hour(start: datetime, end: datetime) -> list[dict]:
    """Hourly post-volume trend for posts CREATED in [start, end). Used for sub-day ranges."""
    import json as _json
    sql = (
        "SELECT a.data AS adata, "
        "       CAST(json_extract(r.data, '$.created_timestamp') AS REAL) AS cts "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ?"
    )
    rows = _storage._conn.execute(sql, [start.timestamp(), end.timestamp()]).fetchall()
    by_hour: dict[str, Counter] = {}
    for row in rows:
        h = datetime.fromtimestamp(row["cts"], tz=timezone.utc).strftime("%Y-%m-%d %H:00")
        a = _json.loads(row["adata"])
        b = by_hour.setdefault(h, Counter())
        b["total_posts"] += 1
        b[a.get("sentiment", "neutral")] += 1
    # Generate every hour bucket in window so the chart has a continuous x-axis.
    trend = []
    cursor = start.replace(minute=0, second=0, microsecond=0)
    end_floor = end.replace(minute=0, second=0, microsecond=0)
    while cursor <= end_floor:
        key = cursor.strftime("%Y-%m-%d %H:00")
        bucket = by_hour.get(key, Counter())
        trend.append({
            "date": cursor.strftime("%H:00"),
            "total_posts": bucket.get("total_posts", 0),
            "sentiment_distribution": {
                "positive": bucket.get("positive", 0),
                "negative": bucket.get("negative", 0),
                "neutral": bucket.get("neutral", 0),
            },
        })
        cursor += timedelta(hours=1)
    return trend


def _compute_top_issues_from_window(window_stats: dict) -> list[dict]:
    """Top 5 aspects by negative-volume severity for the given window stats."""
    issues = []
    aspect_sentiment = window_stats.get("aspect_sentiment", {})
    for name, counts in aspect_sentiment.items():
        total = sum(counts.values())
        neg = counts.get("negative", 0)
        neg_ratio = neg / total if total else 0
        issues.append({
            "aspect": name,
            "count": total,
            "negative_ratio": round(neg_ratio, 3),
            "severity_score": round(total * neg_ratio, 2),
        })
    issues.sort(key=lambda x: x["severity_score"], reverse=True)
    return issues[:5]


@app.get("/api/brand-health")
def get_brand_health(range: str = Query("today")):
    """Overall brand health: sentiment gauge, volume, aspect heatmap data.

    Window semantics: posts whose *creation* time falls in the selected window.
    """
    _ensure_initialized()
    if range not in _VALID_RANGES:
        return {"message": f"Invalid range. Valid: {_VALID_RANGES}", "data": None}

    window_start, window_end, days_requested, date_label = _resolve_window(range)
    stats = _compute_window_aggregate(window_start, window_end)
    if stats["total_posts"] == 0:
        return {"message": f"No data for selected range ({date_label})", "data": None}

    # Trend granularity: hourly for sub-day ranges, daily otherwise.
    if range in _HOUR_RANGES:
        trend = _compute_trend_by_hour(window_start, window_end)
        trend_granularity = "hour"
    else:
        trend_days = max(7, days_requested)
        trend = _compute_trend_by_post_date(trend_days)
        trend_granularity = "day"
    top_issues = _compute_top_issues_from_window(stats)

    # Count days within the requested window that had at least one post.
    if days_requested > 1 and trend_granularity == "day":
        window_trend_slice = trend[-days_requested:]
        days_with_data = sum(1 for d in window_trend_slice if d["total_posts"] > 0)
    else:
        days_with_data = 1 if stats["total_posts"] > 0 else 0

    response = {
        "date": date_label,
        "range": range,
        "days_requested": days_requested,
        "days_with_data": days_with_data,
        "total_posts": stats["total_posts"],
        "trend_granularity": trend_granularity,
        "trusted_posts": stats["trusted_posts"],
        "sentiment_distribution": stats["sentiment_distribution"],
        "aspect_breakdown": stats["aspect_breakdown"],
        "subreddit_distribution": stats["subreddit_distribution"],
        "trend_7d": trend,
        "top_issues": top_issues,
    }
    if days_requested > 1 and days_with_data < days_requested:
        response["fallback_note"] = (
            f"Only {days_with_data} of the last {days_requested} days have data — "
            f"longer ranges will look similar until older history is ingested."
        )
    return response


# ─── P0: Aspect Drilldown ─────────────────────────────────────────────────────

@app.get("/api/aspects/{aspect}")
def get_aspect_drilldown(
    aspect: str,
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(25, ge=1, le=500),
    range: str | None = Query(None, description="Optional range token (matches /api/brand-health). Overrides `days` for the post filter."),
):
    """Deep-dive into a specific aspect: trend + paginated posts.

    Posts are filtered by their *creation* timestamp so the drilldown stays
    consistent with the Brand Health card that was clicked from.
    """
    _ensure_initialized()
    import json as _json

    now = datetime.now(timezone.utc)
    if range and range in _VALID_RANGES:
        window_start, window_end, effective_days, _ = _resolve_window(range)
    else:
        window_end = now
        window_start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        effective_days = days

    # Trend bucketed by post creation date (intersected with aspect mention)
    base_trend_days = max(7, effective_days)
    trend_start = (now - timedelta(days=base_trend_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    trend_sql = (
        "SELECT CAST(json_extract(r.data, '$.created_timestamp') AS REAL) AS cts "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE json_extract(a.data, '$.aspects') LIKE ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ?"
    )
    trend_rows = _storage._conn.execute(
        trend_sql, [f"%{aspect}%", trend_start.timestamp(), now.timestamp()]
    ).fetchall()
    by_date: dict[str, int] = {}
    for row in trend_rows:
        d = datetime.fromtimestamp(row["cts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_date[d] = by_date.get(d, 0) + 1
    trend = []
    for i in range_builtin(base_trend_days, 0, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": d, "total_posts": by_date.get(d, 0)})

    # Posts in window, newest first by post creation
    posts_sql = (
        "SELECT a.data AS adata, r.data AS rdata "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE json_extract(a.data, '$.aspects') LIKE ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ? "
        "ORDER BY CAST(json_extract(r.data, '$.created_timestamp') AS REAL) DESC "
        "LIMIT ?"
    )
    rows = _storage._conn.execute(
        posts_sql, [f"%{aspect}%", window_start.timestamp(), window_end.timestamp(), limit]
    ).fetchall()

    posts = []
    for row in rows:
        a = _json.loads(row["adata"])
        raw = _json.loads(row["rdata"]) if row["rdata"] else {}
        post_id = a.get("post_id", "")

        reddit_url = ""
        if raw.get("url"):
            reddit_url = raw["url"]
        elif post_id.startswith("reddit_"):
            bare = post_id[len("reddit_"):]
            reddit_url = f"https://www.reddit.com/r/{a.get('subreddit', '')}/comments/{bare}/"

        posts.append({
            "id": a.get("id", ""),
            "post_id": post_id,
            "sentiment": a.get("sentiment", "neutral"),
            "sentiment_confidence": a.get("sentiment_confidence", 0),
            "subreddit": a.get("subreddit", ""),
            "analyzed_at": a.get("analyzed_at", ""),
            "trust_score": a.get("trust_score", 0),
            "title": raw.get("title", ""),
            "text": raw.get("body", raw.get("title", "")),
            "author": raw.get("author", ""),
            "score": raw.get("score", 0),
            "created_timestamp": raw.get("created_timestamp", 0),
            "reddit_url": reddit_url,
        })

    return {
        "aspect": aspect,
        "range": range,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "trend": trend,
        "posts": posts,
        "limit": limit,
        "returned": len(posts),
    }


@app.get("/api/aspects")
def list_aspects():
    """List all available aspects with current counts."""
    _ensure_initialized()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    agg = _storage.get_item("aggregates", f"agg_{today}_daily", today)
    if not agg:
        return {"aspects": _config.analysis.aspects, "breakdown": {}}
    return {
        "aspects": _config.analysis.aspects,
        "breakdown": agg.get("aspect_breakdown", {}),
    }


# ─── P0: Review & Validate (HITL) ─────────────────────────────────────────────

def _aspect_names(aspects) -> list[str]:
    """Normalize aspects (mix of str and {aspect: name}) to a flat list of names."""
    out = []
    for a in aspects or []:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict) and a.get("aspect"):
            out.append(a["aspect"])
    return out


# Lazy-loaded LLM client used for reply generation. We keep it module-level so
# the FLAN-T5 model is loaded once per API process, then reused for every draft.
_reply_llm = None


def _get_reply_llm():
    """Return a shared LLM client instance for reply generation."""
    global _reply_llm
    if _reply_llm is None:
        from src.analysis.llm_client import create_llm_client
        from src.utils.cost_tracker import CostTracker
        tracker = CostTracker(_config.llm.cost_log_file) if _config else None
        _reply_llm = create_llm_client(_config.llm, tracker)
        log.info("reply_llm_initialized", model=_reply_llm.model_name)
    return _reply_llm


def _collect_reply_examples(limit: int = 5) -> list[dict]:
    """Pull the most recent analyst-posted replies + their original posts so the
    LLM can learn the brand's preferred tone. This is what makes drafts improve
    over time as analysts post more replies."""
    rows = _storage.query(
        "feedback",
        "SELECT data FROM feedback WHERE json_extract(data, '$.kind') = 'auto_reply_posted' "
        "ORDER BY json_extract(data, '$.created_at') DESC LIMIT ?",
        [limit],
    )
    examples = []
    for r in rows:
        post_id = r.get("post_id", "")
        raw = _storage.get_item("raw_posts", post_id, "")
        post_text = ""
        if raw:
            post_text = (raw.get("title", "") + " " + raw.get("body", "")).strip()
        examples.append({
            "post_text": post_text[:500],
            "reply_text": r.get("reply_text", "")[:500],
        })
    return [e for e in examples if e["reply_text"]]


@app.get("/api/review")
def get_review_queue(limit: int = Query(20, ge=1, le=100)):
    """Get posts needing human review (low confidence or flagged)."""
    _ensure_initialized()
    query = (
        "SELECT data FROM analyses "
        "WHERE json_extract(data, '$.needs_review') = 1 "
        "ORDER BY json_extract(data, '$.analyzed_at') DESC "
        "LIMIT ?"
    )
    analyses = _storage.query("analyses", query, [limit])

    # Enrich with post data
    enriched = []
    for item in analyses:
        post_id = item.get("post_id", "")
        post = _storage.get_item("raw_posts", post_id, item.get("subreddit", ""))

        # Prefer the real permalink stored on the post; otherwise build from the
        # bare reddit id (strip the "reddit_" prefix). Seed posts have neither —
        # leave empty so the UI can hide the link.
        reddit_url = ""
        if post and post.get("url"):
            reddit_url = post["url"]
        elif post_id.startswith("reddit_"):
            bare = post_id[len("reddit_") :]
            reddit_url = f"https://www.reddit.com/r/{item.get('subreddit', '')}/comments/{bare}/"

        enriched_item = {
            "id": item.get("id", ""),
            "post_id": post_id,
            "sentiment": item.get("sentiment", "unknown"),
            "sentiment_confidence": item.get("sentiment_confidence", 0),
            "trust_score": item.get("trust_score", 0),
            "is_trusted": item.get("is_trusted", False),
            "aspects": item.get("aspects", []),
            "needs_review": item.get("needs_review", True),
            "subreddit": item.get("subreddit", ""),
            "analyzed_at": item.get("analyzed_at", ""),
            "model": item.get("model", ""),
            # Post details
            "text": post.get("body", post.get("title", "")) if post else "",
            "title": post.get("title", "") if post else "",
            "author": post.get("author", "") if post else "",
            "score": post.get("score", 0) if post else 0,
            "created_timestamp": post.get("created_timestamp", 0) if post else 0,
            "reddit_url": reddit_url,
            # Auto-reply is generated on demand via /api/review/{id}/draft-reply.
            # We only flag whether the card is eligible (negative posts only).
            "can_generate_reply": item.get("sentiment") == "negative",
            "reply_posted_at": item.get("reply_posted_at"),
            "reply_text": item.get("reply_text", ""),
        }
        enriched.append(enriched_item)

    return {"queue": enriched, "total": len(enriched)}


@app.post("/api/review/{post_id}")
def submit_review(post_id: str, correction: dict):
    """Submit a human correction. Persists to feedback AND updates the analysis
    so it leaves the review queue and the corrected sentiment is reflected
    everywhere (brand health, drilldown, post explorer).

    The feedback table is the audit log; analyses is the source of truth.
    """
    _ensure_initialized()
    now = datetime.now(timezone.utc).isoformat()

    feedback = {
        "id": f"fb_{post_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "post_id": post_id,
        "analyst_id": correction.get("analyst_id", "default"),
        "original_sentiment": correction.get("original_sentiment"),
        "corrected_sentiment": correction.get("corrected_sentiment"),
        "original_aspects": correction.get("original_aspects", []),
        "corrected_aspects": correction.get("corrected_aspects", []),
        "trust_override": correction.get("trust_override"),
        "notes": correction.get("notes", ""),
        "created_at": now,
        "partition_key": correction.get("analyst_id", "default"),
    }
    _storage.upsert("feedback", feedback)

    # Update the analysis record so this post leaves the queue and the corrected
    # value flows through to all aggregations.
    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, correction.get("subreddit", ""))
    if analysis:
        corrected = correction.get("corrected_sentiment")
        if corrected:
            analysis["sentiment"] = corrected
            analysis["sentiment_confidence"] = 1.0  # Human-validated
        analysis["needs_review"] = False
        analysis["human_validated"] = True
        analysis["validated_at"] = now
        analysis["validated_by"] = correction.get("analyst_id", "default")
        _storage.upsert("analyses", analysis)
        log.info(
            "review_correction_applied",
            post_id=post_id,
            from_sentiment=correction.get("original_sentiment"),
            to_sentiment=corrected,
        )
    else:
        log.warning("review_analysis_not_found", post_id=post_id, analysis_id=analysis_id)

    return {
        "status": "saved",
        "feedback_id": feedback["id"],
        "analysis_updated": analysis is not None,
    }


@app.post("/api/review/{post_id}/draft-reply")
def draft_reply(post_id: str, payload: dict | None = None):
    """Generate a customer-specific reply draft for a negative post.

    Pulls the original post + analysis, then asks the configured LLM to draft
    a reply using the last N analyst-posted replies as few-shot examples.
    This is the "learning" loop: every reply an analyst posts becomes training
    context for future drafts.

    Runs synchronously — the first call lazy-loads the generator model, so
    expect ~5-20s on cold start; subsequent calls are fast.
    """
    _ensure_initialized()
    payload = payload or {}
    subreddit = payload.get("subreddit", "")

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, subreddit)
    if not analysis:
        return {"status": "error", "reason": "analysis_not_found"}

    if analysis.get("sentiment") != "negative":
        return {"status": "error", "reason": "not_negative"}

    raw = _storage.get_item("raw_posts", post_id, subreddit) or {}
    aspects = _aspect_names(analysis.get("aspects", []))
    examples = _collect_reply_examples(limit=5)

    try:
        llm = _get_reply_llm()
        result = llm.generate_reply_pair(
            post_title=raw.get("title", ""),
            post_text=raw.get("body", "") or raw.get("title", ""),
            subreddit=analysis.get("subreddit", ""),
            author=raw.get("author", ""),
            aspects=aspects,
            examples=examples,
        )
    except Exception as e:
        log.error("draft_reply_failed", post_id=post_id, error=str(e))
        return {"status": "error", "reason": str(e)}

    drafts = result.get("drafts", [])
    log.info(
        "draft_reply_generated",
        post_id=post_id,
        examples_used=len(examples),
        drafts=[(d.get("source"), d.get("model_used")) for d in drafts],
    )
    # Pick the "primary" draft for callers that still want a single reply
    # field — defaults to the first draft (smart composer).
    primary = drafts[0] if drafts else {}
    return {
        "status": "ok",
        "drafts": drafts,
        "reply": primary.get("reply", ""),
        "model_used": primary.get("model_used", ""),
        "source": primary.get("source", ""),
        "examples_used": len(examples),
    }


@app.post("/api/review/{post_id}/reply")
def save_reply(post_id: str, payload: dict):
    """Persist the analyst-edited reply to the audit log + analysis record."""
    _ensure_initialized()
    now = datetime.now(timezone.utc).isoformat()
    reply_text = (payload.get("reply_text") or "").strip()
    if not reply_text:
        return {"status": "error", "reason": "empty_reply"}

    fb = {
        "id": f"reply_{post_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "post_id": post_id,
        "analyst_id": payload.get("analyst_id", "default"),
        "kind": "auto_reply_posted",
        "reply_text": reply_text,
        "created_at": now,
        "partition_key": payload.get("analyst_id", "default"),
    }
    _storage.upsert("feedback", fb)

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, payload.get("subreddit", ""))
    if analysis:
        analysis["reply_posted_at"] = now
        analysis["reply_text"] = reply_text
        _storage.upsert("analyses", analysis)
    log.info("auto_reply_saved", post_id=post_id, length=len(reply_text))
    return {"status": "saved", "feedback_id": fb["id"], "reply_posted_at": now}


@app.get("/api/review/stats")
def review_stats():
    """Counts of how many corrections have been applied — proof that the
    feedback loop is working. Used for the 'LLM is learning' indicator.
    """
    _ensure_initialized()
    rows = _storage.query("feedback", "SELECT data FROM feedback", [])
    corrections = [
        r for r in rows
        if r.get("corrected_sentiment") and r.get("original_sentiment")
        and r["corrected_sentiment"] != r["original_sentiment"]
    ]
    by_pair: Counter = Counter()
    for r in corrections:
        by_pair[(r["original_sentiment"], r["corrected_sentiment"])] += 1
    replies = [r for r in rows if r.get("kind") == "auto_reply_posted"]
    return {
        "total_feedback": len(rows),
        "total_corrections": len(corrections),
        "total_replies_posted": len(replies),
        "correction_matrix": {f"{k[0]}->{k[1]}": v for k, v in by_pair.items()},
    }



# ─── P1: Alert Feed ────────────────────────────────────────────────────────────

@app.get("/api/alerts")
def get_alerts():
    """Get all current alerts."""
    _ensure_initialized()
    alerts = _alert_engine.detect_all()
    return {"alerts": alerts, "count": len(alerts)}


# ─── P1: Post Explorer ─────────────────────────────────────────────────────────

@app.get("/api/posts")
def search_posts(
    subreddit: str = Query(None),
    sentiment: str = Query(None),
    aspect: str = Query(None),
    trust_min: float = Query(None, ge=0, le=1),
    range: str = Query(None),
    tz_offset: int = Query(None, description="Browser timezone offset in minutes west of UTC (Date.getTimezoneOffset())"),
    limit: int = Query(50, ge=1, le=500),
):
    """Search and filter posts/comments. Joins analyses for sentiment/aspect filters
    and returns a flat enriched record (post fields + sentiment + reddit_url).

    Filtering and sorting both use the post's own `created_timestamp` (when the
    Reddit user authored it), not `analyzed_at` (when our pipeline ran). That
    way "Last 24h" really means posts created in the last 24h, and most-recent
    posts always appear first.
    """
    _ensure_initialized()

    # Resolve time window as a unix timestamp (matches raw_posts.created_timestamp).
    now = datetime.now(timezone.utc)
    since_ts: float | None = None
    if range and range in _HOUR_RANGES:
        since_ts = (now - timedelta(hours=_HOUR_RANGES[range])).timestamp()
    elif range and range in _DAY_RANGES:
        offset_days, days_back = _DAY_RANGES[range]
        if days_back == 1:
            # Single-day window — anchor on the user's local midnight when the
            # browser told us its tz_offset; otherwise fall back to UTC midnight.
            if tz_offset is not None:
                local_now = now - timedelta(minutes=tz_offset)
                local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                anchor_utc = local_midnight + timedelta(minutes=tz_offset)
            else:
                anchor_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
            since_ts = (anchor_utc - timedelta(days=offset_days)).timestamp()
        else:
            since_ts = (now - timedelta(days=days_back)).timestamp()

    where = []
    params: list = []
    if subreddit:
        where.append("a.subreddit = ?")
        params.append(subreddit)
    if sentiment:
        where.append("json_extract(a.data, '$.sentiment') = ?")
        params.append(sentiment)
    if aspect:
        where.append("json_extract(a.data, '$.aspects') LIKE ?")
        params.append(f"%{aspect}%")
    if since_ts is not None:
        # Use post creation time, not pipeline-analyzed time. Coalesce in case
        # an older row is missing created_timestamp.
        where.append(
            "COALESCE(CAST(json_extract(p.data, '$.created_timestamp') AS REAL), 0) >= ?"
        )
        params.append(since_ts)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    sql = (
        "SELECT a.data AS adata, p.data AS pdata "
        "FROM analyses a "
        "LEFT JOIN raw_posts p ON p.id = a.post_id "
        f"{where_sql} "
        "ORDER BY COALESCE(CAST(json_extract(p.data, '$.created_timestamp') AS REAL), 0) DESC LIMIT ?"
    )
    try:
        cursor = _storage._conn.execute(sql, params)  # type: ignore[attr-defined]
        rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001
        log.error("posts_query_failed", error=str(e))
        return {"posts": [], "count": 0, "error": str(e)}

    out = []
    import json as _json
    for row in rows:
        a = _json.loads(row["adata"]) if row["adata"] else {}
        p = _json.loads(row["pdata"]) if row["pdata"] else {}
        post_id = a.get("post_id", "")
        reddit_url = ""
        if p.get("url"):
            reddit_url = p["url"]
        elif post_id.startswith("reddit_"):
            bare = post_id[len("reddit_"):]
            reddit_url = f"https://www.reddit.com/r/{a.get('subreddit', '')}/comments/{bare}/"
        ts = a.get("trust_score") if a.get("trust_score") is not None else p.get("trust_score", 0)
        if trust_min is not None and (ts or 0) < trust_min:
            continue
        out.append({
            "id": a.get("id", ""),
            "post_id": post_id,
            "sentiment": a.get("sentiment", "neutral"),
            "sentiment_confidence": a.get("sentiment_confidence", 0),
            "subreddit": a.get("subreddit", ""),
            "trust_score": ts,
            "human_validated": a.get("human_validated", False),
            "title": p.get("title", ""),
            "text": p.get("body", p.get("title", "")),
            "author": p.get("author", ""),
            "score": p.get("score", 0),
            "created_timestamp": p.get("created_timestamp", 0),
            "analyzed_at": a.get("analyzed_at", ""),
            "aspects": a.get("aspects", []),
            "reddit_url": reddit_url,
        })
    return {"posts": out, "count": len(out)}


# ─── P2: Trust Analytics ───────────────────────────────────────────────────────

@app.get("/api/trust-stats")
def get_trust_stats():
    """Trust filter analytics: distribution, filter rate, flag breakdown."""
    _ensure_initialized()
    query = "SELECT data FROM raw_posts ORDER BY created_timestamp DESC LIMIT 500"
    recent = _storage.query("raw_posts", query, [])

    if not recent:
        return {"total": 0, "trusted": 0, "flagged": 0}

    trusted = sum(1 for p in recent if p.get("trust_score", 0) >= _config.trust.threshold)
    flagged = len(recent) - trusted

    # Trust score distribution (buckets)
    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for p in recent:
        score = p.get("trust_score", 0) or 0
        if score < 0.2:
            buckets["0.0-0.2"] += 1
        elif score < 0.4:
            buckets["0.2-0.4"] += 1
        elif score < 0.6:
            buckets["0.4-0.6"] += 1
        elif score < 0.8:
            buckets["0.6-0.8"] += 1
        else:
            buckets["0.8-1.0"] += 1

    return {
        "total": len(recent),
        "trusted": trusted,
        "flagged": flagged,
        "trust_rate": round(trusted / max(len(recent), 1), 3),
        "distribution": buckets,
    }


# ─── WebSocket: Real-time Alerts ──────────────────────────────────────────────

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint for real-time alert streaming."""
    await websocket.accept()
    _ws_connections.append(websocket)
    log.info("ws_connected", total=len(_ws_connections))

    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Client can send "ping" to keep alive
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _ws_connections.remove(websocket)
        log.info("ws_disconnected", total=len(_ws_connections))


async def broadcast_alert(alert: dict):
    """Broadcast an alert to all connected WebSocket clients."""
    for ws in _ws_connections[:]:
        try:
            await ws.send_json({"type": "alert", "data": alert})
        except Exception:
            _ws_connections.remove(ws)


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def start_dashboard():
    """Start the dashboard server."""
    import uvicorn
    config = load_config()
    uvicorn.run(
        "src.dashboard.api:app",
        host=config.dashboard.host,
        port=config.dashboard.port,
        reload=True,
    )


if __name__ == "__main__":
    start_dashboard()
