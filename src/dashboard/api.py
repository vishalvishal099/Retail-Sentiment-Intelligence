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
from src.utils.segments import segment_for, all_segments, segment_label, UNKNOWN_SEGMENT
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


async def _run_pipeline_subprocess(trigger: str, extra_args: list[str] | None = None,
                                   params: dict | None = None) -> dict:
    """Run one pipeline cycle as a detached subprocess and update state.

    Uses the same Python interpreter the API is running under so we inherit the
    correct virtual environment. Captures stdout/stderr tail for the UI and
    inserts a row into the `pipeline_runs` table on completion so the Pipeline
    page can show run history with counters.
    """
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running", "state": _pipeline_state}

    async with _pipeline_lock:
        if _pipeline_state["running"]:
            return {"started": False, "reason": "already_running", "state": _pipeline_state}
        run_id = uuid.uuid4().hex[:12]
        started_iso = datetime.now(timezone.utc).isoformat()
        _pipeline_state.update(
            running=True,
            last_run_id=run_id,
            last_started_at=started_iso,
            last_finished_at=None,
            last_status=None,
            last_exit_code=None,
            last_trigger=trigger,
        )
        log.info("pipeline_run_started", run_id=run_id, trigger=trigger)
        # Insert a "running" row so the UI can show in-flight jobs.
        _record_pipeline_run(
            run_id=run_id, started_at=started_iso, status="running",
            trigger=trigger, params=params,
        )

    started_at_mono = datetime.now(timezone.utc)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_PROJECT_ROOT)
    cmd_args = [sys.executable, "-m", "src.pipeline", "--once"]
    if extra_args:
        cmd_args.extend(extra_args)
    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout_bytes, _ = await proc.communicate()
    output = (stdout_bytes or b"").decode(errors="replace")
    tail = output.strip().splitlines()[-25:]
    status = "success" if proc.returncode == 0 else "failed"
    finished_iso = datetime.now(timezone.utc).isoformat()
    duration_ms = int((datetime.now(timezone.utc) - started_at_mono).total_seconds() * 1000)
    counters = _parse_counters_from_log_tail(tail)
    _pipeline_state.update(
        running=False,
        last_finished_at=finished_iso,
        last_status=status,
        last_exit_code=proc.returncode,
        last_log_tail=tail,
    )
    _record_pipeline_run(
        run_id=run_id, started_at=started_iso, status=status,
        trigger=trigger, params=params, finished_at=finished_iso,
        duration_ms=duration_ms, counters=counters, log_tail=tail,
        error=None if status == "success" else f"exit_code={proc.returncode}",
    )
    log.info("pipeline_run_finished", run_id=run_id, status=status, code=proc.returncode,
             duration_ms=duration_ms)
    return {"started": True, "run_id": run_id, "state": _pipeline_state}


_COUNTER_KEYS = {
    "ingested", "processed", "trusted", "flagged", "analyzed",
    "candidates", "captioned", "size", "trusted_so_far",
}


def _parse_counters_from_log_tail(tail: list[str]) -> dict:
    """Extract `cycle_complete` and `stage_complete` counter lines from the
    pipeline's stdout into a single dict. Best-effort — works with the
    structlog text formatter used by src/utils/logger.py."""
    import re
    counters: dict = {}
    for line in tail:
        # e.g. "cycle_complete [ingested=12 processed=12 trusted=8 ...]"
        m = re.search(r"(cycle_complete|stage_complete|analyze_pending_start|"
                      r"analyze_pending_batch)\s*\[(.*)\]", line)
        if not m:
            continue
        event, kvs = m.group(1), m.group(2)
        for kv in re.finditer(r"(\w+)=([\w\.\-:/]+)", kvs):
            k, v = kv.group(1), kv.group(2)
            if k in _COUNTER_KEYS:
                try:
                    counters[k] = max(counters.get(k, 0), int(v))
                except ValueError:
                    pass
            elif k == "stage":
                counters.setdefault("stages", []).append(v)
    return counters


def _record_pipeline_run(
    run_id: str,
    started_at: str,
    status: str,
    trigger: str,
    params: dict | None = None,
    finished_at: str | None = None,
    duration_ms: int | None = None,
    counters: dict | None = None,
    log_tail: list[str] | None = None,
    error: str | None = None,
) -> None:
    """Insert or update a row in `pipeline_runs`. Fails soft."""
    if _storage is None:
        return
    import json as _json
    try:
        _storage._conn.execute(
            """INSERT OR REPLACE INTO pipeline_runs
               (id, started_at, finished_at, status, trigger, duration_ms,
                counters_json, params_json, error, log_tail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, started_at, finished_at, status, trigger, duration_ms,
             _json.dumps(counters or {}), _json.dumps(params or {}),
             error, "\n".join(log_tail or [])),
        )
        _storage._conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_run_record_failed", run_id=run_id, error=str(e))


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
    _backfill_segments_if_needed()
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
        _backfill_segments_if_needed()


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


# ─── Pipeline page: data sources, funnel, jobs, registry CRUD ────────────────
# Everything below powers the /pipeline page in the dashboard. See
# frontend/src/pages/Pipeline.tsx.


@app.get("/api/ingestion/funnel")
def ingestion_funnel(range: str = Query("week"), segment: str | None = None):
    """Funnel: fetched → deduped (implicit, we only store unique) → English →
    long enough → analyzed → trusted. Plus a media-type breakdown so the
    Pipeline page can show "how many text vs image vs both".

    All numbers come from `raw_posts` for the requested window (post creation
    time, same convention as Brand Health).
    """
    _ensure_initialized()
    import json as _json
    start, end, _days, _label = _resolve_window(range)
    start_ts, end_ts = start.timestamp(), end.timestamp()

    seg_clause = ""
    seg_params: list = []
    if segment:
        seg_clause = " AND json_extract(data, '$.segment') = ?"
        seg_params = [segment]

    # 1. Total stored (== fetched-and-kept; the dedup happens before insert)
    fetched = _storage._conn.execute(
        f"SELECT COUNT(*) FROM raw_posts WHERE created_timestamp >= ? AND created_timestamp < ?{seg_clause}",
        [start_ts, end_ts, *seg_params],
    ).fetchone()[0]

    # 2-4. Walk each row once to compute the post-storage filter counts +
    # media-type breakdown. Cheap because we only touch the window.
    rows = _storage._conn.execute(
        f"SELECT data FROM raw_posts WHERE created_timestamp >= ? AND created_timestamp < ?{seg_clause}",
        [start_ts, end_ts, *seg_params],
    ).fetchall()
    english = 0
    long_enough = 0
    media_buckets = {"text_only": 0, "image_only": 0, "text_plus_image": 0, "video": 0, "link_only": 0}
    captioned = 0
    for r in rows:
        try:
            d = _json.loads(r["data"])
        except Exception:
            continue
        title = (d.get("title") or "").strip()
        body = (d.get("body") or "").strip()
        media_url = (d.get("media_url") or "").strip()
        is_video = bool(d.get("is_video"))
        has_text = bool(title or body)
        has_image = bool(media_url)
        # English / length proxies — preprocess already filtered, so anything
        # we kept is by definition english+long enough. We still report the
        # counts so the funnel shows non-zero arrows.
        if has_text or has_image:
            english += 1
            if len(title) + len(body) >= 10 or has_image:
                long_enough += 1
        if is_video:
            media_buckets["video"] += 1
        elif has_text and has_image:
            media_buckets["text_plus_image"] += 1
        elif has_image:
            media_buckets["image_only"] += 1
        elif has_text:
            media_buckets["text_only"] += 1
        else:
            media_buckets["link_only"] += 1
        if d.get("image_caption"):
            captioned += 1

    # analyzed = posts in this window that have any analyses row at all.
    # Counted via the analyses table to stay consistent with `trusted`
    # (which is also computed off the analyses join below).
    analyzed = _storage._conn.execute(
        f"""SELECT COUNT(DISTINCT a.post_id) FROM analyses a
            JOIN raw_posts r ON a.post_id = r.id
            WHERE r.created_timestamp >= ? AND r.created_timestamp < ?{seg_clause.replace('data', 'r.data')}""",
        [start_ts, end_ts, *seg_params],
    ).fetchone()[0]

    # 5. Trusted — go through the analyses table so we use the same gate as
    # the rest of the dashboard.
    trusted = 0
    analyses_rows = _storage._conn.execute(
        f"""SELECT a.data FROM analyses a
            JOIN raw_posts r ON a.post_id = r.id
            WHERE r.created_timestamp >= ? AND r.created_timestamp < ?{seg_clause.replace('data', 'r.data')}""",
        [start_ts, end_ts, *seg_params],
    ).fetchall()
    for ar in analyses_rows:
        try:
            an = _json.loads(ar["data"])
        except Exception:
            continue
        if _is_trusted_analysis(an):
            trusted += 1

    images_total = media_buckets["image_only"] + media_buckets["text_plus_image"]
    pct_captioned = round(100 * captioned / images_total, 1) if images_total else 0.0

    return {
        "range": range,
        "segment": segment,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "funnel": [
            {"stage": "fetched",     "count": fetched,     "drop_from_prev": 0},
            {"stage": "english",     "count": english,     "drop_from_prev": max(fetched - english, 0)},
            {"stage": "long_enough", "count": long_enough, "drop_from_prev": max(english - long_enough, 0)},
            {"stage": "analyzed",    "count": analyzed,    "drop_from_prev": max(long_enough - analyzed, 0)},
            {"stage": "trusted",     "count": trusted,     "drop_from_prev": max(analyzed - trusted, 0)},
        ],
        "media_breakdown": {
            **media_buckets,
            "images_total": images_total,
            "captioned": captioned,
            "pct_captioned": pct_captioned,
        },
    }


@app.get("/api/ingestion/sources")
def ingestion_sources(range: str = Query("week")):
    """Per-subreddit ingestion table for the Pipeline page."""
    _ensure_initialized()
    import json as _json
    start, end, _days, _label = _resolve_window(range)
    start_ts, end_ts = start.timestamp(), end.timestamp()

    # Volumes per sub in window. `analyzed` is counted via the analyses
    # table (join on post_id) — `raw_posts.processing_status` is not always
    # flipped reliably, so we treat "has any analyses row" as analyzed.
    rows = _storage._conn.execute(
        """SELECT r.subreddit,
                  COUNT(*) AS cnt,
                  SUM(CASE WHEN a.post_id IS NOT NULL THEN 1 ELSE 0 END) AS analyzed,
                  SUM(CASE WHEN a.post_id IS NULL THEN 1 ELSE 0 END) AS pending,
                  MAX(r.created_timestamp) AS last_created
           FROM raw_posts r
           LEFT JOIN analyses a ON a.post_id = r.id
           WHERE r.created_timestamp >= ? AND r.created_timestamp < ?
           GROUP BY r.subreddit""",
        [start_ts, end_ts],
    ).fetchall()
    counts = {r["subreddit"]: dict(r) for r in rows}

    # Last-fetch info from cursors table
    cursor_rows = _storage._conn.execute(
        "SELECT subreddit, last_fetched_utc, updated_at FROM cursors"
    ).fetchall()
    cursors = {c["subreddit"]: dict(c) for c in cursor_rows}

    from src.ingestion.subreddit_registry import load_all
    entries = load_all()

    items = []
    for e in entries:
        c = counts.get(e.subreddit, {})
        cur = cursors.get(e.subreddit, {})
        items.append({
            "subreddit": e.subreddit,
            "segment": e.segment,
            "enabled": e.enabled,
            "fetched": int(c.get("cnt") or 0),
            "analyzed": int(c.get("analyzed") or 0),
            "pending": int(c.get("pending") or 0),
            "last_created_ts": c.get("last_created"),
            "last_fetched_utc": cur.get("last_fetched_utc"),
            "last_fetched_at": cur.get("updated_at"),
            "subscribers": e.subscribers,
        })
    # Sort: enabled first, then by fetched desc
    items.sort(key=lambda x: (not x["enabled"], -x["fetched"]))
    return {"range": range, "sources": items, "total": len(items)}


@app.get("/api/ingestion/subreddits")
def ingestion_list_subreddits():
    """Full subreddit registry — used by the editor on the Pipeline page."""
    _ensure_initialized()
    from src.ingestion.subreddit_registry import load_all
    entries = load_all()
    return {
        "subreddits": [
            {
                "subreddit": e.subreddit,
                "group": e.group,
                "segment": e.segment,
                "subscribers": e.subscribers,
                "enabled": e.enabled,
                "subreddit_type": e.subreddit_type,
            } for e in entries
        ],
        "total": len(entries),
        "enabled_count": sum(1 for e in entries if e.enabled),
    }


@app.post("/api/ingestion/subreddits/toggle")
async def ingestion_toggle_subreddits(body: dict):
    """Body: {"changes": {"walmart": true, "Costco": false, ...}}"""
    _ensure_initialized()
    from src.ingestion.subreddit_registry import set_enabled
    changes = body.get("changes") or {}
    if not isinstance(changes, dict):
        return {"error": "changes must be a dict"}
    result = set_enabled(changes)
    return {"updated": result["updated"], "changes": result["changes"]}


@app.post("/api/ingestion/subreddits/add")
async def ingestion_add_subreddit(body: dict):
    """Body: {"subreddit": "MyNewSub", "group": "Walmart core", "enabled": true}"""
    _ensure_initialized()
    from src.ingestion.subreddit_registry import upsert
    name = (body.get("subreddit") or "").strip()
    if not name:
        return {"error": "subreddit name required"}
    entry = upsert(
        name=name,
        group=(body.get("group") or "").strip(),
        enabled=bool(body.get("enabled", True)),
    )
    return {"added": entry.subreddit, "segment": entry.segment, "enabled": entry.enabled}


@app.post("/api/ingestion/subreddits/remove")
async def ingestion_remove_subreddit(body: dict):
    """Body: {"subreddit": "MyOldSub"}"""
    _ensure_initialized()
    from src.ingestion.subreddit_registry import remove
    name = (body.get("subreddit") or "").strip()
    if not name:
        return {"error": "subreddit name required"}
    removed = remove(name)
    return {"removed": removed, "subreddit": name}


@app.post("/api/ingestion/backfill")
async def ingestion_backfill(body: dict, background_tasks: BackgroundTasks):
    """Trigger a one-off backfill cycle for the selected subreddits and window.
    Body: {"from": "2026-05-01T00:00:00Z", "to": "2026-06-01T00:00:00Z",
           "subreddits": ["walmart", "Costco"] (optional)}

    Implementation: writes the requested subs to the registry as enabled,
    flips others to disabled for the duration of this run, kicks off a normal
    pipeline cycle with backfill params recorded for the jobs log, then
    restores the original enabled set.

    Constraints: window max 1 year.
    """
    _ensure_initialized()
    from datetime import datetime as _dt
    from src.ingestion.subreddit_registry import load_all, save_all

    try:
        from_dt = _dt.fromisoformat((body.get("from") or "").replace("Z", "+00:00"))
        to_dt = _dt.fromisoformat((body.get("to") or "").replace("Z", "+00:00"))
    except Exception:
        return {"started": False, "reason": "invalid date format; use ISO 8601"}
    if from_dt >= to_dt:
        return {"started": False, "reason": "from must be < to"}
    if (to_dt - from_dt).days > 366:
        return {"started": False, "reason": "window exceeds 1 year (max 366 days)"}

    selected_subs: list[str] = [s.strip() for s in (body.get("subreddits") or []) if s.strip()]
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running"}

    # Save current enabled state so we can restore it after the run.
    entries = load_all()
    original_state = {e.subreddit: e.enabled for e in entries}
    if selected_subs:
        sel_lower = {s.lower() for s in selected_subs}
        for e in entries:
            e.enabled = e.subreddit.lower() in sel_lower
        save_all(entries)

    async def _run_then_restore():
        try:
            await _run_pipeline_subprocess(
                trigger="backfill",
                params={
                    "from": body.get("from"),
                    "to": body.get("to"),
                    "subreddits": selected_subs or "all_currently_enabled",
                },
            )
        finally:
            if selected_subs:
                try:
                    cur = load_all()
                    for e in cur:
                        if e.subreddit in original_state:
                            e.enabled = original_state[e.subreddit]
                    save_all(cur)
                    log.info("backfill_enabled_state_restored", count=len(original_state))
                except Exception as ex:  # noqa: BLE001
                    log.error("backfill_restore_failed", error=str(ex))

    background_tasks.add_task(_run_then_restore)
    return {
        "started": True,
        "window": {"from": body.get("from"), "to": body.get("to"),
                   "days": (to_dt - from_dt).days},
        "subreddits": selected_subs or "all_currently_enabled",
    }


@app.get("/api/jobs/recent")
def jobs_recent(limit: int = Query(25, ge=1, le=200), status: str | None = None):
    """Recent pipeline runs — manual + scheduled + backfill. Powers the
    'Recent jobs' table on the Pipeline page."""
    _ensure_initialized()
    import json as _json
    sql = "SELECT * FROM pipeline_runs"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    try:
        rows = _storage._conn.execute(sql, params).fetchall()
    except Exception as e:  # noqa: BLE001
        # Table may not exist yet on a stale DB; report empty rather than 500.
        log.warning("jobs_query_failed", error=str(e))
        return {"jobs": [], "total": 0}
    jobs = []
    for r in rows:
        d = dict(r)
        # Parse JSON cols for the UI
        try:
            d["counters"] = _json.loads(d.pop("counters_json") or "{}")
        except Exception:
            d["counters"] = {}
        try:
            d["params"] = _json.loads(d.pop("params_json") or "{}")
        except Exception:
            d["params"] = {}
        # log_tail is line-joined; split for the UI
        log_tail = d.pop("log_tail", "") or ""
        d["log_tail"] = log_tail.splitlines() if log_tail else []
        jobs.append(d)
    return {"jobs": jobs, "total": len(jobs)}


@app.get("/api/jobs/{job_id}")
def jobs_detail(job_id: str):
    """Full detail for a single job — log tail, counters, params."""
    _ensure_initialized()
    import json as _json
    try:
        row = _storage._conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", [job_id]
        ).fetchone()
    except Exception as e:  # noqa: BLE001
        return {"error": "lookup_failed", "detail": str(e)}
    if not row:
        return {"error": "not_found", "job_id": job_id}
    d = dict(row)
    try:
        d["counters"] = _json.loads(d.pop("counters_json") or "{}")
    except Exception:
        d["counters"] = {}
    try:
        d["params"] = _json.loads(d.pop("params_json") or "{}")
    except Exception:
        d["params"] = {}
    log_tail = d.pop("log_tail", "") or ""
    d["log_tail"] = log_tail.splitlines() if log_tail else []
    return d


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


# ─── Trust gating (single source of truth) ────────────────────────────────────
#
# Phase 1: every "trusted" count on the dashboard goes through this helper so
# all pages agree on the same universe. Default formula:
#
#     is_trusted := trust_score * sentiment_confidence >= tau
#
# `tau` defaults to 0.35 (see config/pipeline_config.yaml `trust.gate_tau`).
# Set `trust.gate_formula: "legacy"` to fall back to the old `trust_score >= 0.5`.

def _is_trusted_analysis(analysis: dict) -> bool:
    """Whether an analysis row counts as 'trusted' for dashboard display."""
    ts = analysis.get("trust_score")
    if ts is None:
        return False
    cfg = _config.trust if _config else None
    formula = (cfg.gate_formula if cfg else "score_x_confidence")
    if formula == "legacy":
        return ts >= (cfg.threshold if cfg else 0.5)
    # score_x_confidence (default)
    sc = analysis.get("sentiment_confidence")
    if sc is None:
        # No sentiment confidence yet — fall back to a friendlier cutoff so we
        # don't punish older analyses that pre-date Phase 1.
        return ts >= (cfg.threshold if cfg else 0.5)
    tau = cfg.gate_tau if cfg else 0.35
    return (ts * sc) >= tau


def _trust_gate_info() -> dict:
    """Small descriptor of the active trust gate — surfaced in the API for the UI."""
    cfg = _config.trust if _config else None
    formula = cfg.gate_formula if cfg else "score_x_confidence"
    return {
        "formula": formula,
        "tau": cfg.gate_tau if cfg and formula == "score_x_confidence" else None,
        "threshold": cfg.threshold if cfg else 0.5,
    }


# ─── Segments ─────────────────────────────────────────────────────────────────

def _segment_of_post_row(rdata_json: str) -> str:
    """Pull `segment` from a stored raw_post row, falling back to a CSV lookup."""
    import json as _json
    try:
        r = _json.loads(rdata_json) if rdata_json else {}
    except Exception:  # noqa: BLE001
        r = {}
    seg = (r.get("segment") or "").strip()
    if seg:
        return seg
    return segment_for(r.get("subreddit", ""))


def _backfill_segments_if_needed() -> None:
    """One-time pass: stamp `segment` on every raw_post that doesn't already have one.

    Runs on API startup. Cheap on repeat — the WHERE clause finds zero rows once
    the field is populated.
    """
    if _storage is None:
        return
    try:
        rows = _storage._conn.execute(
            "SELECT id, data FROM raw_posts "
            "WHERE json_extract(data, '$.segment') IS NULL OR json_extract(data, '$.segment') = ''"
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("segment_backfill_skipped", error=str(e))
        return
    if not rows:
        log.info("segment_backfill_noop", rows=0)
        return
    import json as _json
    updated = 0
    for row in rows:
        try:
            data = _json.loads(row["data"])
            seg = segment_for(data.get("subreddit", ""))
            if not seg or seg == UNKNOWN_SEGMENT:
                # still write so we don't re-scan it next boot
                seg = UNKNOWN_SEGMENT
            data["segment"] = seg
            _storage._conn.execute(
                "UPDATE raw_posts SET data = ? WHERE id = ?",
                [_json.dumps(data), row["id"]],
            )
            updated += 1
        except Exception as e:  # noqa: BLE001
            log.warning("segment_backfill_row_failed", id=row["id"], error=str(e))
    _storage._conn.commit()
    log.info("segment_backfill_complete", updated=updated)


def _compute_window_aggregate(start: datetime, end: datetime, segment: str | None = None) -> dict:
    """Totals + sentiment + aspects + subreddits for posts CREATED in [start, end).

    `segment` (optional) restricts to a single segment slug. Counting of
    `trusted_posts` goes through `_is_trusted_analysis` so every page agrees on
    the same gate.
    """
    import json as _json
    rows = _fetch_window_rows(start, end)
    sentiment_dist: Counter = Counter()
    aspect_counts: Counter = Counter()
    aspect_sentiment: dict[str, Counter] = {}
    subreddit_dist: Counter = Counter()
    segment_dist: Counter = Counter()
    trusted = 0
    kept = 0
    for row in rows:
        a = _json.loads(row["adata"])
        r = _json.loads(row["rdata"]) if row["rdata"] else {}
        row_segment = (r.get("segment") or segment_for(r.get("subreddit", a.get("subreddit", "")))) or UNKNOWN_SEGMENT
        if segment and row_segment != segment:
            continue
        kept += 1
        sentiment = a.get("sentiment", "neutral")
        sentiment_dist[sentiment] += 1
        if _is_trusted_analysis(a):
            trusted += 1
        sub = a.get("subreddit", "")
        if sub:
            subreddit_dist[sub] += 1
        segment_dist[row_segment] += 1
        for asp in a.get("aspects", []) or []:
            name = asp if isinstance(asp, str) else (asp.get("aspect") if isinstance(asp, dict) else None)
            if not name:
                continue
            aspect_counts[name] += 1
            aspect_sentiment.setdefault(name, Counter())[sentiment] += 1
    return {
        "total_posts": kept,
        "trusted_posts": trusted,
        "sentiment_distribution": {
            "positive": sentiment_dist.get("positive", 0),
            "negative": sentiment_dist.get("negative", 0),
            "neutral": sentiment_dist.get("neutral", 0),
        },
        "aspect_breakdown": dict(aspect_counts),
        "aspect_sentiment": {k: dict(v) for k, v in aspect_sentiment.items()},
        "subreddit_distribution": dict(subreddit_dist),
        "segment_distribution": dict(segment_dist),
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
def get_brand_health(
    range: str = Query("today"),
    segment: str | None = Query(None, description="Optional segment slug to filter by (see /api/segments)."),
):
    """Overall brand health: sentiment gauge, volume, aspect heatmap data.

    Window semantics: posts whose *creation* time falls in the selected window.
    Segment semantics: when `segment` is set, only posts whose subreddit maps
    to that segment are counted (see config/segments).
    """
    _ensure_initialized()
    if range not in _VALID_RANGES:
        return {"message": f"Invalid range. Valid: {_VALID_RANGES}", "data": None}

    window_start, window_end, days_requested, date_label = _resolve_window(range)
    stats = _compute_window_aggregate(window_start, window_end, segment=segment)
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
        "segment": segment,
        "days_requested": days_requested,
        "days_with_data": days_with_data,
        "total_posts": stats["total_posts"],
        "trend_granularity": trend_granularity,
        "trusted_posts": stats["trusted_posts"],
        "trust_gate": _trust_gate_info(),
        "sentiment_distribution": stats["sentiment_distribution"],
        "aspect_breakdown": stats["aspect_breakdown"],
        "subreddit_distribution": stats["subreddit_distribution"],
        "segment_distribution": stats["segment_distribution"],
        "trend_7d": trend,
        "top_issues": top_issues,
    }
    if days_requested > 1 and days_with_data < days_requested:
        response["fallback_note"] = (
            f"Only {days_with_data} of the last {days_requested} days have data — "
            f"longer ranges will look similar until older history is ingested."
        )
    return response


@app.get("/api/segments")
def list_segments():
    """All segment slugs known to the project, with human labels for the UI."""
    return {
        "segments": [
            {"slug": s, "label": segment_label(s)} for s in all_segments()
        ]
    }


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
    segment: str = Query(None, description="Optional segment slug to filter by (see /api/segments)."),
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
    if segment:
        # Push segment into SQL so LIMIT is applied AFTER segment filtering.
        # Older rows that pre-date Phase 2 may have segment NULL; in that case
        # we fall back to a Python-side check below (rare after backfill).
        where.append("json_extract(p.data, '$.segment') = ?")
        params.append(segment)
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
        # Defensive fallback for rows whose JSON had no `segment` at SQL time
        # (would only happen for legacy data pre-Phase 2 backfill).
        if segment:
            row_segment = (p.get("segment") or segment_for(p.get("subreddit", a.get("subreddit", "")))) or UNKNOWN_SEGMENT
            if row_segment != segment:
                continue
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
            "segment": p.get("segment") or segment_for(p.get("subreddit", a.get("subreddit", ""))),
            "trust_score": ts,
            "is_trusted": _is_trusted_analysis(a),
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
    return {"posts": out, "count": len(out), "trust_gate": _trust_gate_info()}


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
