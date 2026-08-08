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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse

from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.utils.segments import segment_for, all_segments, segment_label, UNKNOWN_SEGMENT, macro_segment_for, MACRO_GROUPS, macro_segment_label
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
    "current_stage": None,  # live stage marker parsed from subprocess stdout
    "last_params": None,    # {"lookback_hours": N} — set on start, preserved across runs
    "last_counters": None,  # {"ingested": N, "trusted": N, ...} — updates live
    # Per-subreddit ingest progress for the in-flight run. Keys are sub names;
    # each value carries the timeline + page count so the UI can show
    # "X days reached, Y days remaining, Z% covered, ETA …".
    "ingest_progress": None,
}

# Map pipeline log `stage=...` values onto the UI's stage names.
_STAGE_MAP = {
    "ingest": "ingest",
    "preprocess": "ingest",   # roll preprocess into Ingest in UI
    "vision": "vision",        # image enrichment (gemma caption)
    "trust": "trust",
    "analyze": "analyze",
    "aggregate": "aggregate",
    "alerts": "aggregate",   # alerts run after aggregate; keep UI on Aggregate
}
_pipeline_lock = asyncio.Lock()
_pipeline_proc: asyncio.subprocess.Process | None = None  # live handle so /stop can kill it
_pipeline_stop_requested: bool = False
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PIPELINE_INTERVAL_MINUTES = int(os.environ.get("PIPELINE_INTERVAL_MINUTES", "360"))
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
        # Reset live counters + record params for this run.
        _pipeline_state["last_params"] = dict(params) if params else {}
        _pipeline_state["last_counters"] = {}
        _pipeline_state["ingest_progress"] = {
            "started_at": started_iso,
            "subs": {},          # name -> per-sub progress dict
            "order": [],         # insertion order for stable UI
            "total_subs": 0,
        }
        # Insert a "running" row so the UI can show in-flight jobs.
        _record_pipeline_run(
            run_id=run_id, started_at=started_iso, status="running",
            trigger=trigger, params=params,
        )

    started_at_mono = datetime.now(timezone.utc)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_PROJECT_ROOT)
    # Force unbuffered child stdout so we can read stage events live.
    env.setdefault("PYTHONUNBUFFERED", "1")
    # All HF models are already cached under ~/.cache/huggingface/. Skip the
    # Hub freshness HEAD check so we don't stall 40s per model load when the
    # host is unreachable (off VPN, on corp WiFi with DPI, etc.). Users who
    # want to pull an updated weight can unset these to re-enable checks.
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    # The API runs in .venv (fastapi only). The pipeline needs the ML stack
    # (transformers/torch); allow overriding the interpreter via env var so
    # we can point at /opt/miniconda3/bin/python without duplicating 2 GB of
    # wheels into .venv.
    pipeline_python = os.environ.get("PIPELINE_PYTHON", sys.executable)
    cmd_args = [pipeline_python, "-u", "-m", "src.pipeline"]
    # `--once` is the default cycle mode; standalone modes
    # (--retry-vision, --analyze-pending, --fill-gaps) replace it entirely.
    standalone_modes = {"--retry-vision", "--analyze-pending", "--fill-gaps"}
    if extra_args and any(a in standalone_modes for a in extra_args):
        cmd_args.extend(extra_args)
    else:
        cmd_args.append("--once")
        if extra_args:
            cmd_args.extend(extra_args)
    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    global _pipeline_proc, _pipeline_stop_requested
    _pipeline_proc = proc
    _pipeline_stop_requested = False

    # Stream lines as they arrive so `last_log_tail` + `current_stage`
    # update while the cycle is still running (UI no longer sits on a
    # static elapsed-time guess).
    import re as _re
    _stage_re = _re.compile(r"stage_complete\s*\[stage=(\w+)([^\]]*)\]")
    _cycle_re = _re.compile(r"cycle_complete\s*\[([^\]]*)\]")
    _ingest_start_re = _re.compile(r"(backfill_start|cycle_start|arctic_shift_fetch_complete)")
    _sub_start_re = _re.compile(r"subreddit_fetch_start\s*\[([^\]]*)\]")
    _sub_prog_re = _re.compile(r"subreddit_fetch_progress\s*\[([^\]]*)\]")
    _sub_done_re = _re.compile(r"subreddit_fetch_complete\s*\[([^\]]*)\]")
    collected: list[str] = []
    assert proc.stdout is not None
    _pipeline_state["current_stage"] = "ingest"
    while True:
        line_bytes = await proc.stdout.readline()
        if not line_bytes:
            break
        line = line_bytes.decode(errors="replace").rstrip("\n")
        collected.append(line)
        if len(collected) > 200:
            del collected[: len(collected) - 200]
        _pipeline_state["last_log_tail"] = collected[-25:]
        m = _stage_re.search(line)
        if m:
            stage_raw = m.group(1).lower()
            mapped = _STAGE_MAP.get(stage_raw)
            if mapped:
                _pipeline_state["current_stage"] = mapped
            _merge_stage_counters(
                _pipeline_state["last_counters"], stage_raw, m.group(2),
            )
        elif _ingest_start_re.search(line) and _pipeline_state["current_stage"] is None:
            _pipeline_state["current_stage"] = "ingest"
        cm = _cycle_re.search(line)
        if cm:
            _merge_cycle_counters(_pipeline_state["last_counters"], cm.group(1))
        sm = _sub_start_re.search(line)
        if sm:
            _apply_sub_event(_pipeline_state["ingest_progress"], "start", sm.group(1))
        pm = _sub_prog_re.search(line)
        if pm:
            _apply_sub_event(_pipeline_state["ingest_progress"], "progress", pm.group(1))
        dm = _sub_done_re.search(line)
        if dm:
            _apply_sub_event(_pipeline_state["ingest_progress"], "complete", dm.group(1))
    await proc.wait()
    output = "\n".join(collected)
    tail = collected[-25:]
    if _pipeline_stop_requested:
        status = "stopped"
    else:
        status = "success" if proc.returncode == 0 else "failed"
    finished_iso = datetime.now(timezone.utc).isoformat()
    duration_ms = int((datetime.now(timezone.utc) - started_at_mono).total_seconds() * 1000)
    counters = dict(_pipeline_state.get("last_counters") or {})
    # Fall back to log-tail parsing only if the live parser missed everything.
    if not counters:
        counters = _parse_counters_from_log_tail(tail)
    _pipeline_state["last_counters"] = counters
    _pipeline_state.update(
        running=False,
        last_finished_at=finished_iso,
        last_status=status,
        last_exit_code=proc.returncode,
        last_log_tail=tail,
        current_stage=None,
    )
    _pipeline_proc = None
    _pipeline_stop_requested = False
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


# Maps `stage_complete [stage=<raw> ...]` kwargs onto canonical counter keys
# the UI consumes. Format: { raw_stage: { source_kwarg: canonical_key } }.
_STAGE_COUNTER_MAP: dict[str, dict[str, str]] = {
    "ingest":     {"count": "ingested"},
    "preprocess": {"count": "processed"},
    "vision":     {"candidates": "vision_candidates", "captioned": "captioned"},
    "trust":      {"trusted": "trusted", "flagged": "flagged"},
    "analyze":    {"count": "analyzed"},
    "alerts":     {"count": "alerts"},
}


def _merge_stage_counters(counters: dict | None, stage_raw: str, kvs: str) -> None:
    """Update live counters from a single `stage_complete` log line."""
    if counters is None:
        return
    mapping = _STAGE_COUNTER_MAP.get(stage_raw)
    if not mapping:
        return
    import re as _re
    for kv in _re.finditer(r"(\w+)=(-?\d+)", kvs):
        k, v = kv.group(1), kv.group(2)
        canonical = mapping.get(k)
        if canonical:
            try:
                counters[canonical] = int(v)
            except ValueError:
                pass


def _merge_cycle_counters(counters: dict | None, kvs: str) -> None:
    """Update live counters from a `cycle_complete` log line (terminal totals)."""
    if counters is None:
        return
    import re as _re
    for kv in _re.finditer(r"(\w+)=(-?\d+)", kvs):
        k, v = kv.group(1), kv.group(2)
        if k in _COUNTER_KEYS:
            try:
                counters[k] = int(v)
            except ValueError:
                pass


def _parse_kv_pairs(kvs: str) -> dict:
    """Cheap parser for `key=value` tokens from a structlog text line.
    Numeric strings are coerced to int/float; everything else stays str."""
    import re as _re
    out: dict = {}
    for kv in _re.finditer(r"(\w+)=([\w\.\-:/+]+)", kvs):
        k, v = kv.group(1), kv.group(2)
        # Try int then float; fall back to str.
        try:
            out[k] = int(v)
            continue
        except ValueError:
            pass
        try:
            out[k] = float(v)
            continue
        except ValueError:
            pass
        out[k] = v
    return out


def _apply_sub_event(progress: dict | None, kind: str, kvs: str) -> None:
    """Update per-subreddit ingest progress from a single log line."""
    if progress is None:
        return
    kv = _parse_kv_pairs(kvs)
    sub = kv.get("subreddit")
    if not sub:
        return
    now = datetime.now(timezone.utc).isoformat()
    subs = progress.setdefault("subs", {})
    order = progress.setdefault("order", [])
    if sub not in subs:
        subs[sub] = {
            "subreddit": sub,
            "since_utc": kv.get("since_utc"),
            "until_utc": kv.get("until_utc"),
            "position": kv.get("position"),
            "total_subs": kv.get("total_subs"),
            "fetch_limit": kv.get("fetch_limit"),
            "window_days": kv.get("window_days"),
            "oldest_utc": None,
            "newest_utc": None,
            "page_size": 0,
            "total_fetched": 0,
            "coverage_pct": 0.0,
            "status": "pending",
            "started_at": now,
            "last_update": now,
        }
        order.append(sub)
    record = subs[sub]
    record["last_update"] = now
    if kind == "start":
        record["status"] = "running"
        for f in ("since_utc", "until_utc", "position", "total_subs",
                  "fetch_limit", "window_days"):
            if f in kv:
                record[f] = kv[f]
        if "total_subs" in kv:
            progress["total_subs"] = kv["total_subs"]
    elif kind == "progress":
        record["status"] = "running"
        for f in ("oldest_utc", "newest_utc", "page_size", "total_fetched",
                  "coverage_pct"):
            if f in kv:
                record[f] = kv[f]
        # Recompute coverage_pct here too (defensive — log may round).
        try:
            since = float(record.get("since_utc") or 0)
            until = float(record.get("until_utc") or 0)
            oldest = float(record.get("oldest_utc") or until)
            window = max(1.0, until - since)
            covered = max(0.0, min(window, until - oldest))
            record["coverage_pct"] = round(100.0 * covered / window, 1)
        except (TypeError, ValueError):
            pass
    elif kind == "complete":
        record["status"] = kv.get("status", "ok")
        if "fetched" in kv:
            record["total_fetched"] = kv["fetched"]
        record["coverage_pct"] = 100.0
        record["finished_at"] = now


def _summarize_ingest_progress(progress: dict | None) -> dict | None:
    """Aggregate per-sub progress into an overall % + ETA for the UI."""
    if not progress or not progress.get("subs"):
        return None
    subs = progress["subs"]
    order = progress.get("order", list(subs.keys()))
    total = progress.get("total_subs") or len(subs) or 1
    subs_done = sum(1 for r in subs.values() if r.get("status") in {"ok", "failed"})
    # Average coverage across all subs we expect (counts not-yet-started
    # subs as 0%, which gives a more honest "I haven't even started those
    # yet" view during long runs).
    cov_sum = sum((r.get("coverage_pct") or 0.0) for r in subs.values())
    overall_pct = round(cov_sum / total, 1) if total else 0.0
    # ETA based on elapsed wall time vs. overall_pct. Quiet during the first
    # 5% so the first page (which is always slow) doesn't blow it up.
    eta_seconds = None
    started = progress.get("started_at")
    if started and overall_pct >= 5.0 and overall_pct < 100.0:
        try:
            t0 = datetime.fromisoformat(started)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            if elapsed > 0:
                eta_seconds = int(elapsed * (100.0 - overall_pct) / overall_pct)
        except ValueError:
            pass
    return {
        "started_at": started,
        "subs_total": total,
        "subs_done": subs_done,
        "overall_pct": overall_pct,
        "eta_seconds": eta_seconds,
        "subreddits": [subs[name] for name in order if name in subs],
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

@app.get("/")
def root():
    return {
        "service": "Retail Sentiment Intelligence API",
        "status": "ok",
        "docs": "/docs",
        "endpoints": ["/api/brand-health", "/api/posts", "/api/alerts", "/api/aspects", "/api/pipeline/status"],
        "frontend": "http://localhost:3001",
    }


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
    # Cumulative DB-side totals so the UI can show "as-of-now" counts that
    # survive across runs (counters reset every cycle; these don't).
    totals = _pipeline_totals()
    summary = _summarize_ingest_progress(_pipeline_state.get("ingest_progress"))
    return {
        **_pipeline_state,
        "ingest_progress": summary,
        "interval_minutes": _PIPELINE_INTERVAL_MINUTES,
        "scheduler_enabled": _scheduler_task is not None and not _scheduler_task.done(),
        "scheduler_started_at": _scheduler_started_at.isoformat() if _scheduler_started_at else None,
        "next_scheduled_run_at": next_run.isoformat() if next_run else None,
        "totals": totals,
    }


def _pipeline_totals() -> dict:
    """Cumulative counts pulled straight from the database. Fail-soft.

    Opens a short-lived read-only SQLite connection so we never share the
    main `_storage._conn` with concurrent funnel/sources queries (that mix
    raised `returned NULL without setting an exception` on Python 3.13).
    """
    out = {
        "raw_posts": 0,
        "trusted_posts": 0,
        "analyzed_posts": 0,
        "ingested_today": 0,
        "ingested_24h": 0,
    }
    if _config is None:
        return out
    import sqlite3
    from datetime import datetime, timezone
    conn = None
    try:
        db_path = _config.storage.sqlite_path
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, timeout=2.0,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_totals_connect_failed", error=str(e))
        return out

    # `is_trusted` lives inside the JSON `data` blob, not as a column.
    queries: list[tuple[str, str, tuple]] = [
        ("raw_posts",       "SELECT COUNT(*) FROM raw_posts", ()),
        ("trusted_posts",   "SELECT COUNT(*) FROM raw_posts WHERE json_extract(data, '$.is_trusted') = 1", ()),
        ("analyzed_posts",  "SELECT COUNT(*) FROM analyses", ()),
    ]
    now_ts = datetime.now(timezone.utc).timestamp()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).timestamp()
    queries.append(("ingested_24h",
        "SELECT COUNT(*) FROM raw_posts WHERE created_timestamp >= ?", (now_ts - 86400,)))
    queries.append(("ingested_today",
        "SELECT COUNT(*) FROM raw_posts WHERE created_timestamp >= ?", (today_start,)))

    try:
        for key, sql, params in queries:
            try:
                out[key] = int(conn.execute(sql, params).fetchone()[0] or 0)
            except Exception as e:  # noqa: BLE001
                log.warning("pipeline_totals_query_failed", key=key, error=str(e))
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return out


@app.post("/api/pipeline/run")
async def pipeline_run(background_tasks: BackgroundTasks, lookback_hours: int | None = None):
    """Trigger an immediate pipeline cycle. Returns 409-style payload if already running.
    Optional lookback_hours overrides the default fetch window (1-4320 hours = 6 months).
    """
    if _pipeline_state["running"]:
        return {
            "started": False,
            "reason": "already_running",
            "state": _pipeline_state,
        }
    extra_args: list[str] = []
    params: dict | None = None
    if lookback_hours and 1 <= lookback_hours <= 4320:
        extra_args = ["--lookback-hours", str(lookback_hours)]
        params = {"lookback_hours": lookback_hours}
    background_tasks.add_task(_run_pipeline_subprocess, "manual", extra_args=extra_args or None, params=params)
    return {"started": True, "state": _pipeline_state}


@app.post("/api/pipeline/stop")
async def pipeline_stop():
    """Cancel the in-flight pipeline cycle, if any.

    Sends SIGTERM to the subprocess, waits up to 5s for graceful exit, then
    SIGKILLs. The stream reader will exit when the pipe closes and the run
    will be recorded with status='stopped'.
    """
    global _pipeline_stop_requested
    proc = _pipeline_proc
    if proc is None or proc.returncode is not None:
        return {"stopped": False, "reason": "not_running", "state": _pipeline_state}
    _pipeline_stop_requested = True
    try:
        proc.terminate()
    except ProcessLookupError:
        return {"stopped": True, "reason": "already_exited", "state": _pipeline_state}
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    log.info("pipeline_run_stopped", run_id=_pipeline_state.get("last_run_id"))
    return {"stopped": True, "state": _pipeline_state}


@app.post("/api/pipeline/retry-vision")
async def pipeline_retry_vision(background_tasks: BackgroundTasks):
    """Re-caption stored raw_posts that have images but no caption.

    Useful after Ollama was down during a backfill. Runs as a background
    subprocess so the request returns immediately; progress shows up in
    the live log panel like a normal run.
    """
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running", "state": _pipeline_state}
    background_tasks.add_task(
        _run_pipeline_subprocess,
        "retry-vision",
        extra_args=["--retry-vision"],
        params={"mode": "retry-vision"},
    )
    return {"started": True, "state": _pipeline_state}


@app.get("/api/pipeline/cursors")
def pipeline_cursors():
    """Per-subreddit ingestion watermarks + most recent fetch window.

    Lets the UI show exactly *what time delta* each scheduled run has
    covered, so analysts can spot gaps (e.g. a subreddit whose
    `last_window.fetched` has been 0 for 3 cycles in a row).

    Each row also carries `newest_post_utc` — the MAX(created_timestamp)
    actually in raw_posts for that sub. This can differ from `last_fetched_utc`
    when a lookback-hours rewind put the cursor behind the data we already
    have (cursor drift). The UI treats freshness against newest_post_utc,
    not the cursor.
    """
    from src.storage.cursor import CursorTracker
    from src.pipeline import INGEST_OVERLAP_SECONDS
    try:
        ct = CursorTracker(_config.storage.sqlite_path) if _config else CursorTracker()
        rows = ct.list_cursors()
        ct.close()
        # Enrich each row with the actual newest post timestamp from raw_posts.
        # One aggregate query, no per-sub roundtrips.
        _ensure_initialized()
        newest = dict(_storage._conn.execute(
            "SELECT subreddit, MAX(created_timestamp) FROM raw_posts GROUP BY subreddit"
        ).fetchall())
        # Case-insensitive match — DB rows sometimes use different casing than the CSV.
        newest_ci = {k.lower(): v for k, v in newest.items() if k}
        for r in rows:
            sub = r.get("subreddit") or ""
            r["newest_post_utc"] = newest_ci.get(sub.lower())
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_cursors_failed", error=str(e))
        rows = []
    return {
        "cursors": rows,
        "overlap_seconds": INGEST_OVERLAP_SECONDS,
        "next_scheduled_run_at": _next_scheduled_run_at.isoformat() if _next_scheduled_run_at else None,
    }


@app.get("/api/pipeline/gaps")
def pipeline_gaps(gap_hours: float = Query(1.0, ge=0.0, le=720.0)):
    """Per-subreddit data-freshness report.

    Pure read: computes the gap between the newest raw_post and now for every
    configured subreddit. Flags subs whose cursor has drifted behind their
    data (a symptom of a lookback-hours rewind that upstream then returned
    zero results for).

    Used by the "Fill gaps" dashboard panel and as the dry-run preview for
    POST /api/pipeline/fill-gaps.
    """
    _ensure_initialized()
    from src.pipeline import RetailSentimentPipeline
    try:
        # Reuse the API's already-initialized components; only compute_gaps
        # is called (pure read, no ingest).
        pl = RetailSentimentPipeline(_config)
        pl.initialize()
        report = pl.compute_gaps(gap_threshold_hours=gap_hours)
        try:
            pl.cursor.close()
        except Exception:  # noqa: BLE001
            pass
        return report
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_gaps_failed", error=str(e))
        return {"error": str(e), "subreddits": [], "totals": {}}


@app.post("/api/pipeline/fill-gaps")
async def pipeline_fill_gaps(
    background_tasks: BackgroundTasks,
    since: str | None = Query(None, description="Anchor timestamp (ISO 8601 UTC). Every sub whose cursor is more recent than this will be rewound to this timestamp. Example: '2026-06-29T00:00:00Z'"),
    gap_hours: float = Query(1.0, ge=0.0, le=720.0, description="Only used when `since` is omitted: skip subs whose gap is smaller than this."),
    dry_run: bool = Query(False, description="If true, returns the plan without touching cursors or running the pipeline."),
):
    """Surgical backfill: rewind only the stale subs and run one cycle.

    Two ways to invoke:
      - Provide `since=YYYY-MM-DDTHH:MM:SSZ` — every subreddit whose cursor
        is more recent than that gets rewound to that timestamp. Matches the
        "last successful run was 29 June, fill everything since then" case.
      - Omit `since` — per-sub auto: rewind each stale sub to just after its
        newest raw_post (minus overlap buffer). Fresh subs are left alone.

    In both modes storage dedupes on `id`, so any refetched posts are
    idempotent.
    """
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running", "state": _pipeline_state}

    # Dry-run short-circuits to the plan; no subprocess is spawned.
    if dry_run:
        _ensure_initialized()
        from src.pipeline import RetailSentimentPipeline
        try:
            pl = RetailSentimentPipeline(_config)
            pl.initialize()
            since_ts: float | None = None
            if since:
                from datetime import datetime, timezone
                try:
                    dtv = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    if dtv.tzinfo is None:
                        dtv = dtv.replace(tzinfo=timezone.utc)
                    since_ts = dtv.timestamp()
                except ValueError:
                    return {"started": False, "reason": "bad_since", "detail": f"{since!r} is not ISO 8601"}
            plan = pl.fill_gaps(since_utc=since_ts, gap_threshold_hours=gap_hours, dry_run=True)
            try:
                pl.cursor.close()
            except Exception:  # noqa: BLE001
                pass
            return {"started": False, "dry_run": True, "plan": plan}
        except Exception as e:  # noqa: BLE001
            return {"started": False, "reason": "dry_run_failed", "detail": str(e)}

    # Apply mode: hand off to the pipeline subprocess with the flags so it
    # runs under PIPELINE_PYTHON with the ML stack available.
    extra_args: list[str] = ["--fill-gaps", "--gap-hours", str(gap_hours)]
    if since:
        extra_args.extend(["--since", since])
    params = {"mode": "fill-gaps", "since": since, "gap_hours": gap_hours}
    background_tasks.add_task(
        _run_pipeline_subprocess,
        "fill-gaps",
        extra_args=extra_args,
        params=params,
    )
    return {"started": True, "state": _pipeline_state, "plan_preview": "see /api/pipeline/gaps"}


@app.get("/api/pipeline/analysis-backlog")
def pipeline_analysis_backlog():
    """How many raw_posts exist without a matching row in `analyses`.

    Cheap SQL count used by the "Analyze pending" button in the Pipeline UI
    so it can show a live badge (e.g. "9,510 pending").
    """
    _ensure_initialized()
    try:
        raw = _storage._conn.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
        ana = _storage._conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        # A tighter measure: raw rows that don't have an analysis row.
        # analyses.post_id references raw_posts.id (analyses.id is prefixed
        # with "analysis_", so joining on id would count every row as pending).
        pending = _storage._conn.execute(
            "SELECT COUNT(*) FROM raw_posts r LEFT JOIN analyses a ON a.post_id = r.id "
            "WHERE a.post_id IS NULL"
        ).fetchone()[0]
        return {"raw_posts": raw, "analyses": ana, "pending": pending}
    except Exception as e:  # noqa: BLE001
        log.warning("analysis_backlog_failed", error=str(e))
        return {"raw_posts": 0, "analyses": 0, "pending": 0, "error": str(e)}


@app.post("/api/pipeline/analyze-pending")
async def pipeline_analyze_pending(
    background_tasks: BackgroundTasks,
    max_batches: int | None = Query(None, ge=1, le=10000),
):
    """Kick a subprocess that runs `python -m src.pipeline --analyze-pending`.

    No network calls — just processes raw_posts already on disk that have
    no analysis row. Uses the same ML interpreter as normal cycles.
    """
    if _pipeline_state["running"]:
        return {"started": False, "reason": "already_running", "state": _pipeline_state}
    extra_args: list[str] = ["--analyze-pending"]
    if max_batches:
        extra_args.extend(["--max-batches", str(max_batches)])
    params = {"mode": "analyze-pending", "max_batches": max_batches}
    background_tasks.add_task(
        _run_pipeline_subprocess,
        "analyze-pending",
        extra_args=extra_args,
        params=params,
    )
    return {"started": True, "state": _pipeline_state}


@app.get("/api/ingestion/image-failures")
def ingestion_image_failures(limit: int = Query(50, ge=1, le=500)):
    """Per-post record of image fetch outcomes.

    Powers the Pipeline UI's "Image availability" panel. Shows the breakdown
    of image-bearing posts by fetch status (fetched / deleted / throttled / …)
    plus the most recent N failed posts so analysts can see WHICH images
    disappeared (Reddit user deleted the post, imgur throttled us, etc.).

    Data source: raw_posts.data.image_fetch, populated by the vision-enrichment
    stage. Posts ingested before this field existed simply don't appear here.
    """
    _ensure_initialized()
    try:
        # Only rows that have an image_fetch object (i.e. we tried to fetch).
        rows = _storage._conn.execute(
            "SELECT id, subreddit, created_timestamp, "
            "       json_extract(data, '$.image_fetch') AS fetch_json, "
            "       json_extract(data, '$.title') AS title, "
            "       json_extract(data, '$.permalink') AS permalink "
            "FROM raw_posts "
            "WHERE json_extract(data, '$.image_fetch') IS NOT NULL "
            "ORDER BY created_timestamp DESC "
            "LIMIT 5000"
        ).fetchall()

        import json as _json
        totals: dict[str, int] = {}
        samples: list[dict] = []
        for r in rows:
            try:
                fetch = _json.loads(r["fetch_json"]) if r["fetch_json"] else None
            except Exception:  # noqa: BLE001
                fetch = None
            if not fetch:
                continue
            status = fetch.get("status", "unknown")
            totals[status] = totals.get(status, 0) + 1
            # Collect only failed samples for the drill-down table.
            if status != "fetched" and len(samples) < limit:
                samples.append({
                    "post_id": r["id"],
                    "subreddit": r["subreddit"],
                    "created_utc": r["created_timestamp"],
                    "title": (r["title"] or "")[:120],
                    "url": fetch.get("url", "")[:150],
                    "status": status,
                    "http_code": fetch.get("http_code"),
                    "error": (fetch.get("error") or "")[:200],
                    "checked_at": fetch.get("checked_at"),
                    "permalink": r["permalink"],
                })

        total_checked = sum(totals.values())
        total_fetched = totals.get("fetched", 0)
        total_failed = total_checked - total_fetched
        return {
            "total_checked": total_checked,
            "total_fetched": total_fetched,
            "total_failed": total_failed,
            "totals_by_status": totals,
            "samples": samples,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("image_failures_query_failed", error=str(e))
        return {
            "total_checked": 0, "total_fetched": 0, "total_failed": 0,
            "totals_by_status": {}, "samples": [], "error": str(e),
        }


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

    # `captioned` counts every post with an `image_caption` field set.
    # The pipeline also captions video thumbnails and link previews, so the
    # raw bucket count (image_only + text_plus_image) can be smaller than
    # `captioned`. Widen the denominator to include video + any extra
    # captions so the percentage never exceeds 100% — what users expect.
    images_total = max(
        media_buckets["image_only"] + media_buckets["text_plus_image"] + media_buckets["video"],
        captioned,
    )
    pct_captioned = round(100 * captioned / images_total, 1) if images_total else 0.0

    # Vision failure breakdown: categorize why images were not captioned
    vision_failures = {"timeout": 0, "fetch_failed": 0, "ollama_unavailable": 0,
                       "no_content": 0, "other": 0}
    uncaptioned = images_total - captioned
    if uncaptioned > 0:
        # Check pipeline_runs log for vision failure patterns (approximate)
        # For now, attribute to ollama_unavailable if Ollama isn't running
        # (which is the dominant case on this machine)
        vision_failures["ollama_unavailable"] = uncaptioned

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
            "vision_failures": vision_failures,
        },
        "funnel_detail": {
            "not_english": max(fetched - english, 0),
            "too_short": max(english - long_enough, 0),
            "not_yet_analyzed": max(long_enough - analyzed, 0),
            "low_trust": max(analyzed - trusted, 0),
            "total_posts": fetched,
            "trust_rate": round(100 * trusted / analyzed, 1) if analyzed else 0,
            "analysis_coverage": round(100 * analyzed / long_enough, 1) if long_enough else 0,
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
            "macro_group": e.macro_group,
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
                "macro_group": e.macro_group,
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
    from src.storage.cursor import CursorTracker

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
        subs_to_run = [e.subreddit for e in entries if e.subreddit.lower() in sel_lower]
    else:
        subs_to_run = [e.subreddit for e in entries if e.enabled]

    # Rewind cursors so the next ingest actually starts at `from`. Without
    # this the pipeline reads cursor.get_cursor(sub) (the last successful
    # watermark) and ignores the requested window entirely.
    from_utc = from_dt.timestamp()
    original_cursors: dict[str, float] = {}
    try:
        ct = CursorTracker(_config.storage.sqlite_path)
        for sub in subs_to_run:
            original_cursors[sub] = ct.get_cursor(sub)
            ct.update_cursor(sub, from_utc, "")
        log.info("backfill_cursors_rewound", count=len(subs_to_run), from_utc=from_utc)
    except Exception as ex:  # noqa: BLE001
        log.error("backfill_cursor_rewind_failed", error=str(ex))

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


# ─── Admin: destructive flush ──────────────────────────────────────────────
# Used by the Pipeline page to wipe local SQLite data and restart from scratch
# (typically followed by a 90-day backfill). Requires explicit ?confirm=YES_DELETE_ALL
# to prevent accidental hits. Always backs up data/local.db first.

@app.post("/api/admin/flush")
async def admin_flush(
    confirm: str = Query("", description="Must be 'YES_DELETE_ALL' to proceed"),
    backup: bool = Query(True, description="Backup data/local.db before flushing"),
):
    """Wipe all data tables (raw_posts, analyses, aggregates, feedback, alerts,
    pipeline_runs, cursors) so the next run rebuilds from scratch.

    Returns the row counts deleted per table and the path of the DB backup
    (if `backup=True`).
    """
    _ensure_initialized()
    if confirm != "YES_DELETE_ALL":
        return {
            "flushed": False,
            "reason": "missing or invalid confirm token (expected 'YES_DELETE_ALL')",
        }
    if _pipeline_state["running"]:
        return {"flushed": False, "reason": "pipeline currently running — wait for it to finish"}

    import shutil
    from pathlib import Path as _Path
    from src.storage.cursor import CursorTracker

    backup_path: str | None = None
    if backup:
        try:
            db_path = _Path(getattr(_storage, "db_path", "data/local.db"))
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = db_path.with_suffix(f".db.bak.{ts}")
            if db_path.exists():
                shutil.copy2(db_path, target)
                backup_path = str(target)
                log.warning("admin_flush_backup_created", path=backup_path)
        except Exception as e:  # noqa: BLE001
            log.error("admin_flush_backup_failed", error=str(e))
            return {"flushed": False, "reason": f"backup failed: {e}"}

    deleted_tables = _storage.flush_all() if hasattr(_storage, "flush_all") else {}

    # Reset cursors so next ingestion starts from scratch
    deleted_cursors = 0
    try:
        ct = CursorTracker(getattr(_storage, "db_path", "data/local.db"))
        deleted_cursors = ct.reset_all()
        ct.close()
    except Exception as e:  # noqa: BLE001
        log.error("admin_flush_cursor_reset_failed", error=str(e))

    log.warning("admin_flush_completed", tables=deleted_tables, cursors=deleted_cursors)
    return {
        "flushed": True,
        "deleted_tables": deleted_tables,
        "deleted_cursors": deleted_cursors,
        "backup_path": backup_path,
    }


# ─── Phase 3: Reddit OAuth (login + callback + status + logout) ─────────────
# Cookie-based, single-process session store. No external deps. The cookie is
# a random session id; the server maps it to a `TokenBundle`. State tokens for
# CSRF are kept alongside until consumed by the callback.

_OAUTH_SESSIONS: dict[str, dict] = {}      # session_id -> {"token": TokenBundle.to_session(), ...}
_OAUTH_PENDING_STATE: dict[str, str] = {}  # session_id -> CSRF state token
_OAUTH_COOKIE = "rsi_session"


def _get_oauth_session_id(request: Request) -> str | None:
    return request.cookies.get(_OAUTH_COOKIE)


def _ensure_oauth_session_id(request: Request, response: Response) -> str:
    sid = request.cookies.get(_OAUTH_COOKIE)
    if not sid:
        import secrets as _secrets
        sid = _secrets.token_urlsafe(24)
        # httponly + samesite=lax so the callback redirect still carries the cookie.
        response.set_cookie(_OAUTH_COOKIE, sid, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return sid


def _clear_oauth_session(sid: str | None) -> None:
    if sid and sid in _OAUTH_SESSIONS:
        del _OAUTH_SESSIONS[sid]
    if sid and sid in _OAUTH_PENDING_STATE:
        del _OAUTH_PENDING_STATE[sid]


@app.get("/api/auth/reddit/login")
def auth_reddit_login(request: Request):
    """Begin the OAuth dance: returns the URL the browser should send the user
    to for Reddit consent. (We don't 302 from here so the SPA can decide how
    to navigate — typically a `window.location.href = ...` assignment.)
    """
    _ensure_initialized()
    cfg = _config.reddit_oauth
    if not cfg.enabled:
        return JSONResponse({"ok": False, "error": "reddit_oauth_disabled"}, status_code=400)
    if cfg.dry_run:
        return JSONResponse({
            "ok": False,
            "dry_run": True,
            "error": "reddit_oauth in dry_run mode — replies are logged, no live login required",
        }, status_code=200)
    if not cfg.client_id or not cfg.client_secret:
        return JSONResponse({
            "ok": False,
            "error": "reddit_oauth.client_id/client_secret not configured",
        }, status_code=400)
    from src.reddit.oauth import build_authorize_url, new_state_token
    response = JSONResponse({"ok": True})
    sid = _ensure_oauth_session_id(request, response)
    state = new_state_token()
    _OAUTH_PENDING_STATE[sid] = state
    url = build_authorize_url(cfg, state)
    response = JSONResponse({"ok": True, "authorize_url": url})
    response.set_cookie(_OAUTH_COOKIE, sid, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return response


@app.get("/api/auth/reddit/callback")
def auth_reddit_callback(request: Request, code: str = Query(""), state: str = Query(""), error: str = Query("")):
    """Reddit redirects the browser here with `?code=...&state=...`.

    We verify the state, exchange the code, stash the token, and 302 the
    browser back to the SPA.
    """
    _ensure_initialized()
    cfg = _config.reddit_oauth
    spa_redirect = "/?reddit_login=success"
    sid = _get_oauth_session_id(request)

    if error:
        log.warning("reddit_oauth_callback_error", error=error)
        return RedirectResponse(f"/?reddit_login=denied&error={error}", status_code=302)

    expected_state = _OAUTH_PENDING_STATE.get(sid or "", "")
    if not state or not expected_state or state != expected_state:
        log.warning("reddit_oauth_state_mismatch", got=state, expected=bool(expected_state))
        return RedirectResponse("/?reddit_login=state_mismatch", status_code=302)
    _OAUTH_PENDING_STATE.pop(sid or "", None)

    try:
        from src.reddit.oauth import exchange_code_for_token
        bundle = exchange_code_for_token(cfg, code)
    except Exception as e:  # noqa: BLE001
        log.error("reddit_oauth_exchange_failed", error=str(e))
        return RedirectResponse("/?reddit_login=exchange_failed", status_code=302)

    if sid:
        _OAUTH_SESSIONS[sid] = {"token": bundle.to_session()}
    log.info("reddit_oauth_session_created", username=bundle.username)
    return RedirectResponse(spa_redirect, status_code=302)


@app.get("/api/auth/reddit/status")
def auth_reddit_status(request: Request):
    """Return whether the current browser session is logged in to Reddit."""
    _ensure_initialized()
    cfg = _config.reddit_oauth
    sid = _get_oauth_session_id(request)
    sess = _OAUTH_SESSIONS.get(sid or "", {}) if sid else {}
    token_data = sess.get("token") or {}

    from src.reddit.oauth import TokenBundle
    bundle = TokenBundle.from_session(token_data) if token_data else None

    return {
        "enabled": cfg.enabled,
        "dry_run": cfg.dry_run,
        "logged_in": bool(bundle and not bundle.is_expired()),
        "username": bundle.username if bundle else "",
        "expires_at": bundle.expires_at if bundle else 0,
        "client_configured": bool(cfg.client_id and cfg.client_secret),
    }


@app.post("/api/auth/reddit/logout")
def auth_reddit_logout(request: Request):
    """Drop the server-side token so the cookie no longer authenticates."""
    sid = _get_oauth_session_id(request)
    _clear_oauth_session(sid)
    log.info("reddit_oauth_logged_out", sid=bool(sid))
    return {"ok": True, "logged_out": True}


def _current_reddit_token(request: Request):
    """Helper used by the reply endpoint. Returns a TokenBundle (refreshed if
    needed) or None if the user is not logged in.
    """
    sid = _get_oauth_session_id(request)
    if not sid:
        return None
    sess = _OAUTH_SESSIONS.get(sid, {})
    token_data = sess.get("token")
    if not token_data:
        return None
    from src.reddit.oauth import TokenBundle, refresh_token
    bundle = TokenBundle.from_session(token_data)
    if not bundle:
        return None
    if bundle.is_expired() and bundle.refresh_token:
        try:
            bundle = refresh_token(_config.reddit_oauth, bundle.refresh_token)
            _OAUTH_SESSIONS[sid] = {"token": bundle.to_session()}
        except Exception as e:  # noqa: BLE001
            log.warning("reddit_oauth_refresh_failed", error=str(e))
            return None
    return bundle


# ─── Phase 4: Post Lifecycle ────────────────────────────────────────────────

LIFECYCLE_STATES = ("new", "acknowledged", "reply_sent", "issue_fixed", "resolved")
_LIFECYCLE_TRANSITIONS = {
    "new": {"reply_sent", "resolved"},
    "acknowledged": {"reply_sent", "resolved"},
    "reply_sent": {"issue_fixed", "resolved"},
    "issue_fixed": {"resolved"},
    "resolved": set(),
}


@app.get("/api/lifecycle")
def lifecycle_list(state: str | None = Query(None), limit: int = Query(200, ge=1, le=1000)):
    """Lifecycle board — counts per state + cards (optionally filtered)."""
    _ensure_initialized()
    if state and state not in LIFECYCLE_STATES:
        return JSONResponse({"error": f"unknown state '{state}'"}, status_code=400)
    rows = _storage.lifecycle_list(state=state, limit=limit)
    counts = _storage.lifecycle_counts()
    counts_full = {s: counts.get(s, 0) for s in LIFECYCLE_STATES}
    for row in rows:
        if row.get("reddit_url"):
            continue
        post_id = row.get("post_id", "")
        subreddit = row.get("subreddit", "")
        try:
            raw = _storage.get_item("raw_posts", post_id, subreddit) or {}
        except Exception:
            raw = {}
        url = raw.get("url") if isinstance(raw, dict) else ""
        if not url and isinstance(post_id, str) and post_id.startswith("reddit_"):
            bare = post_id[len("reddit_"):]
            url = f"https://www.reddit.com/r/{subreddit}/comments/{bare}/"
        if url:
            row["reddit_url"] = url
    return {
        "states": list(LIFECYCLE_STATES),
        "counts": counts_full,
        "rows": rows,
    }


@app.get("/api/lifecycle/{post_id}")
def lifecycle_get(post_id: str):
    _ensure_initialized()
    row = _storage.lifecycle_get(post_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    # Enrich with the latest analysis for display.
    analysis = _storage.get_item("analyses", f"analysis_{post_id}", row.get("subreddit", ""))
    raw = _storage.get_item("raw_posts", post_id, row.get("subreddit", ""))
    return {"lifecycle": row, "analysis": analysis, "raw": raw}


@app.post("/api/lifecycle/{post_id}/transition")
def lifecycle_transition(post_id: str, payload: dict):
    """Move a lifecycle row to a new state. Allowed transitions are validated
    server-side. Logs the transition into `history`.
    """
    _ensure_initialized()
    target = (payload.get("to_state") or "").strip()
    note = (payload.get("note") or "").strip()
    by = (payload.get("by") or "analyst").strip()
    assign_team = (payload.get("assign_team") or "").strip()
    if target not in LIFECYCLE_STATES:
        return JSONResponse({"error": f"unknown state '{target}'"}, status_code=400)

    row = _storage.lifecycle_get(post_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)

    current = row.get("state", "new")
    allowed = _LIFECYCLE_TRANSITIONS.get(current, set())
    if target not in allowed and target != current:
        return JSONResponse(
            {"error": f"transition '{current}' -> '{target}' not allowed",
             "allowed": sorted(allowed)},
            status_code=400,
        )

    now = datetime.now(timezone.utc).isoformat()
    history = row.get("history") or []
    history_note = note if not assign_team else (f"[Assigned: {assign_team}] {note}" if note else f"[Assigned: {assign_team}]")
    history.append({"at": now, "from_state": current, "to_state": target, "by": by, "note": history_note})
    row["state"] = target
    row["history"] = history
    row["updated_at"] = now
    if assign_team:
        row["assign_team"] = assign_team
    if note:
        row["action_note"] = note
    if target == "acknowledged" and not row.get("acknowledged_at"):
        row["acknowledged_at"] = now
    if target == "reply_sent" and not row.get("reply_sent_at"):
        row["reply_sent_at"] = now
    if target == "resolved" and not row.get("resolved_at"):
        row["resolved_at"] = now

    _storage.lifecycle_upsert(row)
    log.info("lifecycle_transition", post_id=post_id, from_state=current, to_state=target, by=by)
    return {"ok": True, "lifecycle": row}


@app.post("/api/lifecycle/{post_id}/resolve")
def lifecycle_resolve(post_id: str, payload: dict):
    """Convenience endpoint: mark a lifecycle row as resolved (skips
    intermediate states). Records optional resolution note in history.
    """
    _ensure_initialized()
    row = _storage.lifecycle_get(post_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    now = datetime.now(timezone.utc).isoformat()
    history = row.get("history") or []
    history.append({
        "at": now,
        "from_state": row.get("state"),
        "to_state": "resolved",
        "by": payload.get("by", "analyst"),
        "note": payload.get("note", ""),
    })
    row["state"] = "resolved"
    row["resolved_at"] = now
    row["updated_at"] = now
    row["history"] = history
    _storage.lifecycle_upsert(row)
    log.info("lifecycle_resolved", post_id=post_id)
    return {"ok": True, "lifecycle": row}


# ─── Phase 5: Competitor Insights ───────────────────────────────────────────

@app.get("/api/insights/latest")
def insights_latest(kind: str = Query("competitor_daily")):
    """Most-recent competitor insights bundle (daily by default)."""
    _ensure_initialized()
    row = _storage.insights_latest(kind=kind)
    if not row:
        return {"available": False, "kind": kind}
    return {"available": True, **row}


@app.get("/api/insights/history")
def insights_history(limit: int = Query(20, ge=1, le=100)):
    _ensure_initialized()
    return {"history": _storage.insights_history(limit=limit)}


@app.post("/api/insights/generate")
def insights_generate(payload: dict | None = None):
    """Trigger an on-demand insights run for the requested window (1-90 days)."""
    _ensure_initialized()
    days = 7
    if payload:
        try:
            days = int(payload.get("window_days", 7))
        except (TypeError, ValueError):
            days = 7
    from src.analysis.competitor_insights import generate_insights
    result = generate_insights(_storage, window_days=days, kind="competitor_on_demand")
    return result


@app.get("/api/competitor-trend")
def competitor_trend(days: int = Query(14, ge=3, le=90), top_n: int = Query(4, ge=1, le=8)):
    """Daily sentiment score per top competitor subreddit, plus a Walmart
    baseline for comparison. Powers the multi-line competitor trend chart
    and the share-of-voice bar chart on the Competitor Insights page.

    Sentiment score per day per subreddit = (positive - negative) / total,
    clamped to [-1, +1]. Days with no posts return null so recharts leaves
    a gap instead of drawing a spurious zero.
    """
    _ensure_initialized()
    import json as _json
    from src.ingestion.subreddit_registry import load_all as _load_all_registry

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Which subreddits count as Walmart vs Competitor, from the registry.
    registry = _load_all_registry()
    walmart_subs = {e.subreddit for e in registry if e.macro_group == "walmart"}
    competitor_subs = {e.subreddit for e in registry if e.macro_group == "competitor"}

    sql = (
        "SELECT a.subreddit AS sub, a.data AS adata, "
        "       CAST(json_extract(r.data, '$.created_timestamp') AS REAL) AS cts "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ?"
    )
    rows = _storage._conn.execute(sql, [start.timestamp(), now.timestamp()]).fetchall()

    # Aggregate: per subreddit, per day, count sentiment.
    per_sub: dict[str, dict[str, Counter]] = {}
    sub_totals: Counter = Counter()
    for row in rows:
        sub = row["sub"] or ""
        try:
            a = _json.loads(row["adata"])
        except Exception:
            continue
        d = datetime.fromtimestamp(row["cts"], tz=timezone.utc).strftime("%Y-%m-%d")
        per_sub.setdefault(sub, {}).setdefault(d, Counter())[a.get("sentiment", "neutral")] += 1
        sub_totals[sub] += 1

    day_keys = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    # Pick the top-N competitors by volume.
    top_competitors = [
        s for s, _ in sub_totals.most_common()
        if s in competitor_subs
    ][:top_n]

    def _series_for(subs: set[str], name: str) -> dict:
        """Build a per-day sentiment score for the union of the given subs."""
        per_day = []
        for d in day_keys:
            pos = neg = tot = 0
            for s in subs:
                c = per_sub.get(s, {}).get(d)
                if not c:
                    continue
                p = c.get("positive", 0); n = c.get("negative", 0)
                pos += p; neg += n; tot += p + n + c.get("neutral", 0)
            score = round((pos - neg) / tot, 4) if tot else None
            per_day.append({"date": d, "score": score, "posts": tot})
        return {"label": name, "subreddits": sorted(subs), "total_posts": sum(sub_totals[s] for s in subs), "points": per_day}

    series: list[dict] = []
    # Walmart baseline first so it renders behind competitors in the chart.
    if walmart_subs:
        series.append(_series_for(walmart_subs, "Walmart"))
    for comp in top_competitors:
        series.append(_series_for({comp}, f"r/{comp}"))

    # Share-of-voice: total post volume per series, over the whole window.
    share_of_voice = [{"label": s["label"], "posts": s["total_posts"]} for s in series]

    return {
        "days": day_keys,
        "series": series,
        "share_of_voice": share_of_voice,
        "walmart_subreddits": sorted(walmart_subs),
        "top_competitors": top_competitors,
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


def _range_to_cutoff(range_token: str) -> str | None:
    """Convert a UI range token to an ISO timestamp cutoff string, or None if unknown."""
    now = datetime.now(timezone.utc)
    if range_token in _HOUR_RANGES:
        cutoff = now - timedelta(hours=_HOUR_RANGES[range_token])
        return cutoff.isoformat()
    if range_token in _DAY_RANGES:
        offset_days, days_back = _DAY_RANGES[range_token]
        cutoff = (now - timedelta(days=offset_days + days_back - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return cutoff.isoformat()
    return None


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


def _compute_window_aggregate(start: datetime, end: datetime, segment: str | None = None, macro_segment: str | None = None) -> dict:
    """Totals + sentiment + aspects + subreddits for posts CREATED in [start, end).

    `segment` (optional) restricts to a single segment slug. Counting of
    `trusted_posts` goes through `_is_trusted_analysis` so every page agrees on
    the same gate.
    `macro_segment` (optional, 'walmart'|'competitor') is layered on top of `segment`.
    """
    import json as _json
    rows = _fetch_window_rows(start, end)
    sentiment_dist: Counter = Counter()
    aspect_counts: Counter = Counter()
    aspect_sentiment: dict[str, Counter] = {}
    subreddit_dist: Counter = Counter()
    segment_dist: Counter = Counter()
    macro_dist: Counter = Counter()
    trusted = 0
    kept = 0
    for row in rows:
        a = _json.loads(row["adata"])
        r = _json.loads(row["rdata"]) if row["rdata"] else {}
        sub = a.get("subreddit", "") or r.get("subreddit", "")
        row_segment = (r.get("segment") or segment_for(sub)) or UNKNOWN_SEGMENT
        row_macro = macro_segment_for(sub)
        if segment and row_segment != segment:
            continue
        if macro_segment and row_macro != macro_segment:
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
        macro_dist[row_macro] += 1
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
        "macro_segment_distribution": dict(macro_dist),
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


@app.get("/api/aspect-heatmap")
def get_aspect_heatmap(
    days: int = Query(7, ge=1, le=30),
    top_n: int = Query(6, ge=1, le=12),
):
    """Aspect × Day heatmap for BrandHealth. Returns the top-N aspects by
    total mentions over the window, along with per-day sentiment counts for
    each aspect. Each cell reports negative_ratio in [0..1] which the UI maps
    to a colour scale (green → yellow → red).
    """
    _ensure_initialized()
    import json as _json
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    sql = (
        "SELECT a.data AS adata, "
        "       CAST(json_extract(r.data, '$.created_timestamp') AS REAL) AS cts "
        "FROM analyses a "
        "JOIN raw_posts r ON r.id = json_extract(a.data, '$.post_id') "
        "WHERE CAST(json_extract(r.data, '$.created_timestamp') AS REAL) >= ? "
        "  AND CAST(json_extract(r.data, '$.created_timestamp') AS REAL) < ?"
    )
    rows = _storage._conn.execute(sql, [start.timestamp(), now.timestamp()]).fetchall()

    # Roll up aspect × day sentiment counts.
    # matrix[aspect][day] = Counter({positive, negative, neutral})
    matrix: dict[str, dict[str, Counter]] = {}
    aspect_totals: Counter = Counter()
    for row in rows:
        try:
            a = _json.loads(row["adata"])
        except Exception:
            continue
        sentiment = a.get("sentiment", "neutral")
        d = datetime.fromtimestamp(row["cts"], tz=timezone.utc).strftime("%Y-%m-%d")
        for asp in _aspect_names(a.get("aspects") or []):
            aspect_totals[asp] += 1
            per_day = matrix.setdefault(asp, {})
            per_day.setdefault(d, Counter())[sentiment] += 1

    top_aspects = [name for name, _ in aspect_totals.most_common(top_n)]

    # Build a continuous list of day buckets for the x-axis.
    day_keys = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    cells = []
    for asp in top_aspects:
        per_day = matrix.get(asp, {})
        for d in day_keys:
            counts = per_day.get(d, Counter())
            total = sum(counts.values())
            neg = counts.get("negative", 0)
            cells.append({
                "aspect": asp,
                "date": d,
                "count": total,
                "positive": counts.get("positive", 0),
                "negative": neg,
                "neutral": counts.get("neutral", 0),
                "negative_ratio": round(neg / total, 3) if total else 0.0,
            })

    return {
        "aspects": top_aspects,
        "days": day_keys,
        "cells": cells,
        "totals": {a: aspect_totals[a] for a in top_aspects},
    }


@app.get("/api/brand-health")
def get_brand_health(
    range: str = Query("today"),
    segment: str | None = Query(None, description="Optional segment slug to filter by (see /api/segments)."),
    macro_segment: str | None = Query(None, description="Optional macro group: 'walmart' or 'competitor'."),
):
    """Overall brand health: sentiment gauge, volume, aspect heatmap data.

    Window semantics: posts whose *creation* time falls in the selected window.
    Segment semantics: when `segment` is set, only posts whose subreddit maps
    to that segment are counted (see config/segments).
    `macro_segment` (Walmart vs Competitor) layers on top of `segment`.
    """
    _ensure_initialized()
    if range not in _VALID_RANGES:
        return {"message": f"Invalid range. Valid: {_VALID_RANGES}", "data": None}
    if macro_segment and macro_segment not in MACRO_GROUPS:
        return {"message": f"Invalid macro_segment. Valid: {list(MACRO_GROUPS)}", "data": None}

    window_start, window_end, days_requested, date_label = _resolve_window(range)
    stats = _compute_window_aggregate(window_start, window_end, segment=segment, macro_segment=macro_segment)
    if stats["total_posts"] == 0:
        return {"message": f"No data for selected range ({date_label})", "data": None}

    # Fetched count = raw_posts in the window (before analysis). Brand Health's
    # `total_posts` is the ANALYZED subset, so `fetched_count` can be higher
    # when there's an analysis backlog. Exposing both lets the UI show
    # "X analyzed of Y fetched (Z pending)" instead of an unexplained mismatch
    # with the Pipeline page.
    fetched_where = ["created_timestamp >= ?", "created_timestamp < ?"]
    fetched_params: list = [window_start.timestamp(), window_end.timestamp()]
    if macro_segment:
        from src.ingestion.subreddit_registry import load_all as _load_all_registry
        macro_subs = [e.subreddit for e in _load_all_registry() if e.macro_group == macro_segment]
        if macro_subs:
            placeholders = ",".join(["?"] * len(macro_subs))
            fetched_where.append(f"subreddit IN ({placeholders})")
            fetched_params.extend(macro_subs)
    if segment:
        fetched_where.append("json_extract(data, '$.segment') = ?")
        fetched_params.append(segment)
    try:
        fetched_count = _storage._conn.execute(
            f"SELECT COUNT(*) FROM raw_posts WHERE {' AND '.join(fetched_where)}",
            fetched_params,
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        fetched_count = stats["total_posts"]

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
        "macro_segment": macro_segment,
        "days_requested": days_requested,
        "days_with_data": days_with_data,
        "total_posts": stats["total_posts"],
        "fetched_count": fetched_count,
        "pending_analysis": max(0, fetched_count - stats["total_posts"]),
        "trend_granularity": trend_granularity,
        "trusted_posts": stats["trusted_posts"],
        "trust_gate": _trust_gate_info(),
        "sentiment_distribution": stats["sentiment_distribution"],
        "aspect_breakdown": stats["aspect_breakdown"],
        "subreddit_distribution": stats["subreddit_distribution"],
        "segment_distribution": stats["segment_distribution"],
        "macro_segment_distribution": stats.get("macro_segment_distribution", {}),
        "trend_7d": trend,
        "top_issues": top_issues,
    }
    if days_requested > 1 and days_with_data < days_requested:
        response["fallback_note"] = (
            f"Only {days_with_data} of the last {days_requested} days have data — "
            f"longer ranges will look similar until older history is ingested."
        )
    return response


@app.get("/api/brand-health/priority-negatives")
def get_priority_negatives(
    range: str = Query("today"),
    segment: str | None = Query(None),
    macro_segment: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Top-N negative posts ranked by `trust_score × sentiment_confidence`.

    Powers the "Priority negative posts" panel on Brand Health. Each row is
    tagged P1 (urgent: trusted + high-confidence) or P2 (medium urgency) so
    the social team can triage. Posts that don't meet either threshold are
    excluded.

    Tier thresholds:
        P1 — trust_score ≥ 0.7 AND sentiment_confidence ≥ 0.8
        P2 — trust_score ≥ 0.5 AND sentiment_confidence ≥ 0.6 (and not P1)
    """
    _ensure_initialized()
    if range not in _VALID_RANGES:
        return {"posts": [], "count": 0, "error": f"Invalid range. Valid: {_VALID_RANGES}"}
    if macro_segment and macro_segment not in MACRO_GROUPS:
        return {"posts": [], "count": 0, "error": f"invalid macro_segment '{macro_segment}'"}

    # Resolve window in the same way /api/posts does so the time filter
    # matches what the analyst sees in the rest of Brand Health.
    now = datetime.now(timezone.utc)
    since_ts: float | None = None
    if range in _HOUR_RANGES:
        since_ts = (now - timedelta(hours=_HOUR_RANGES[range])).timestamp()
    elif range in _DAY_RANGES:
        offset_days, days_back = _DAY_RANGES[range]
        if days_back == 1:
            anchor_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
            since_ts = (anchor_utc - timedelta(days=offset_days)).timestamp()
        else:
            since_ts = (now - timedelta(days=days_back)).timestamp()

    where = ["json_extract(a.data, '$.sentiment') = 'negative'"]
    params: list = []
    if segment:
        where.append("json_extract(p.data, '$.segment') = ?")
        params.append(segment)
    if macro_segment:
        from src.ingestion.subreddit_registry import load_all as _load_all_registry
        macro_subs = [e.subreddit for e in _load_all_registry() if e.macro_group == macro_segment]
        if not macro_subs:
            return {"posts": [], "count": 0, "tiers": {"P1": 0, "P2": 0}}
        placeholders = ",".join(["?"] * len(macro_subs))
        where.append(f"a.subreddit IN ({placeholders})")
        params.extend(macro_subs)
    if since_ts is not None:
        where.append(
            "COALESCE(CAST(json_extract(p.data, '$.created_timestamp') AS REAL), 0) >= ?"
        )
        params.append(since_ts)

    # Over-fetch so we have enough candidates after the priority-tier filter.
    # Cap to a sane upper bound.
    fetch_cap = max(limit * 5, 200)
    where_sql = " WHERE " + " AND ".join(where)
    sql = (
        "SELECT a.data AS adata, p.data AS pdata "
        "FROM analyses a "
        "LEFT JOIN raw_posts p ON p.id = a.post_id "
        f"{where_sql} "
        # Order by the priority score directly in SQL so the LIMIT keeps the
        # top candidates. Tier filtering happens in Python because the
        # threshold logic is cleaner there.
        "ORDER BY ("
        "  COALESCE(CAST(json_extract(a.data, '$.trust_score') AS REAL), 0) "
        "  * COALESCE(CAST(json_extract(a.data, '$.sentiment_confidence') AS REAL), 0)"
        ") DESC LIMIT ?"
    )
    params.append(fetch_cap)

    import json as _json
    try:
        rows = _storage._conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        log.error("priority_negatives_query_failed", error=str(e))
        return {"posts": [], "count": 0, "error": str(e)}

    # ── True tier totals (window-wide, NOT limited to the returned sample) ──
    # A separate COUNT(*) query so `tiers.P1` / `tiers.P2` reflect the whole
    # window regardless of `limit`. Without this, tier_counts stops
    # incrementing once we've collected `limit` posts and the UI shows
    # "P1: 20" for every range.
    tier_counts = {"P1": 0, "P2": 0}
    try:
        count_sql = (
            "SELECT "
            "  SUM(CASE WHEN trust >= 0.7 AND conf >= 0.8 THEN 1 ELSE 0 END) AS p1, "
            "  SUM(CASE WHEN (trust >= 0.5 AND conf >= 0.6) "
            "             AND NOT (trust >= 0.7 AND conf >= 0.8) THEN 1 ELSE 0 END) AS p2 "
            "FROM (SELECT "
            "  COALESCE(CAST(json_extract(a.data, '$.trust_score') AS REAL), 0) AS trust, "
            "  COALESCE(CAST(json_extract(a.data, '$.sentiment_confidence') AS REAL), 0) AS conf "
            "  FROM analyses a LEFT JOIN raw_posts p ON p.id = a.post_id "
            f"  {where_sql}"
            ")"
        )
        # Reuse the exact same where-clause params, minus the trailing LIMIT
        # value that only applied to the sample query.
        count_params = params[:-1]
        row = _storage._conn.execute(count_sql, count_params).fetchone()
        tier_counts["P1"] = int(row["p1"] or 0)
        tier_counts["P2"] = int(row["p2"] or 0)
    except Exception as e:  # noqa: BLE001
        log.warning("priority_negatives_count_failed", error=str(e))

    out: list[dict] = []
    for row in rows:
        a = _json.loads(row["adata"]) if row["adata"] else {}
        p = _json.loads(row["pdata"]) if row["pdata"] else {}
        trust = float(a.get("trust_score") or 0.0)
        conf = float(a.get("sentiment_confidence") or 0.0)
        if trust >= 0.7 and conf >= 0.8:
            tier = "P1"
        elif trust >= 0.5 and conf >= 0.6:
            tier = "P2"
        else:
            continue
        post_id = a.get("post_id", "")
        reddit_url = ""
        if p.get("url"):
            reddit_url = p["url"]
        elif post_id.startswith("reddit_"):
            bare = post_id[len("reddit_"):]
            reddit_url = f"https://www.reddit.com/r/{a.get('subreddit', '')}/comments/{bare}/"
        out.append({
            "post_id": post_id,
            "priority_tier": tier,
            "priority_score": round(trust * conf, 4),
            "sentiment_confidence": round(conf, 3),
            "trust_score": round(trust, 3),
            "subreddit": a.get("subreddit", ""),
            "segment": p.get("segment") or segment_for(p.get("subreddit", a.get("subreddit", ""))),
            "macro_segment": macro_segment_for(a.get("subreddit", "") or p.get("subreddit", "")),
            "title": p.get("title", ""),
            "text": p.get("body", p.get("title", "")),
            "aspects": a.get("aspects", []),
            "author": p.get("author", ""),
            "score": p.get("score", 0),
            "created_timestamp": p.get("created_timestamp", 0),
            "reddit_url": reddit_url,
        })
        if len(out) >= limit:
            break

    return {
        "posts": out,
        "count": len(out),
        "tiers": tier_counts,
        "range": range,
        "limit": limit,
    }


@app.get("/api/segments")
def list_segments():
    """All segment slugs known to the project, with human labels for the UI."""
    return {
        "segments": [
            {"slug": s, "label": segment_label(s)} for s in all_segments()
        ]
    }


@app.get("/api/macro-segments")
def list_macro_segments():
    """Walmart vs Competitor groupings for the BrandHealth toggle."""
    return {
        "macro_segments": [
            {"slug": m, "label": macro_segment_label(m)} for m in MACRO_GROUPS
        ]
    }


# ─── P0: Aspect Drilldown ─────────────────────────────────────────────────────

@app.get("/api/aspects/{aspect:path}")
def get_aspect_drilldown(
    aspect: str,
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(25, ge=1, le=500),
    range: str | None = Query(None, description="Optional range token (matches /api/brand-health). Overrides `days` for the post filter."),
    macro_segment: str | None = Query(None, description="Optional macro group: 'walmart' or 'competitor'."),
):
    """Deep-dive into a specific aspect: trend + paginated posts.

    Uses `:path` so aspect names containing `/` (e.g. "online/app",
    "delivery/pickup") route correctly without needing URL-encoding by the
    client. Posts are filtered by their *creation* timestamp so the
    drilldown stays consistent with the Brand Health card that was clicked
    from.
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

    # Optional macro_segment post-filter (Walmart vs Competitor).
    _macro_filter = macro_segment if macro_segment in MACRO_GROUPS else None

    posts = []
    for row in rows:
        a = _json.loads(row["adata"])
        raw = _json.loads(row["rdata"]) if row["rdata"] else {}
        post_id = a.get("post_id", "")
        sub = a.get("subreddit", "") or raw.get("subreddit", "")
        if _macro_filter and macro_segment_for(sub) != _macro_filter:
            continue

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


def _ensure_lifecycle_reply_sent(post_id: str, analysis: dict | None, now: str):
    """Create or transition a lifecycle row into reply_sent when a reply is saved."""
    try:
        existing = _storage.lifecycle_get(post_id)
        if existing:
            # Already in reply_sent or beyond — nothing to do.
            if existing.get("state") in ("reply_sent", "issue_fixed", "resolved"):
                return
            # Transition to reply_sent regardless of current state.
            existing["state"] = "reply_sent"
            existing["reply_sent_at"] = now
            existing["updated_at"] = now
            _storage.lifecycle_upsert(existing)
        else:
            # Create a new lifecycle entry directly in reply_sent.
            subreddit = (analysis or {}).get("subreddit", "")
            raw = _storage.get_item("raw_posts", post_id, subreddit)
            row = {
                "id": f"lc_{post_id}",
                "post_id": post_id,
                "state": "reply_sent",
                "priority": "medium",
                "subreddit": subreddit,
                "title": (raw or {}).get("title", ""),
                "top_aspect": "",
                "sentiment_score": (analysis or {}).get("sentiment_confidence", 0),
                "sentiment_confidence": (analysis or {}).get("sentiment_confidence", 0),
                "created_at": now,
                "updated_at": now,
                "reply_sent_at": now,
                "partition_key": subreddit,
                # Carry the Ollama caption + source image URL forward so the
                # lifecycle board can render "what the model saw" alongside
                # the post title.
                "image_caption": (raw or {}).get("image_caption", ""),
                "image_url": (raw or {}).get("thumbnail")
                    or (raw or {}).get("url_overridden_by_dest")
                    or (raw or {}).get("preview_url")
                    or "",
            }
            if analysis:
                aspects = analysis.get("aspects", [])
                if aspects:
                    a = aspects[0]
                    row["top_aspect"] = a.get("aspect", "") if isinstance(a, dict) else str(a)
            _storage.lifecycle_upsert(row)
    except Exception as e:
        log.error("lifecycle_reply_sent_auto_failed", post_id=post_id, error=str(e))


@app.get("/api/review")
def get_review_queue(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sentiment: str = Query(None),
    range: str = Query(None, alias="range"),
    macro_segment: str = Query(None, description="Optional macro group: 'walmart' or 'competitor'."),
):
    """Get posts needing human review. When sentiment/range filters are active,
    return ALL matching posts (not just needs_review=1) so the analyst can
    review and reply to any post that matches the criteria."""
    _ensure_initialized()

    macro_subs: set[str] | None = None
    if macro_segment:
        try:
            from src.utils.segments import _load_macro_map
            macro_subs = {s for s, m in _load_macro_map().items() if m == macro_segment}
        except Exception:
            macro_subs = None

    conditions: list[str] = []
    params: list = []

    # Include posts the model flagged for review (low confidence) OR any
    # negative post that clears the P1/P2 priority bar — those need analyst
    # eyes even though the model was confident. Reviewed posts drop out
    # because their `needs_review` is set to False after triage.
    trust_expr_f = "COALESCE(CAST(json_extract(data, '$.trust_score') AS REAL), 0)"
    conf_expr_f = "COALESCE(CAST(json_extract(data, '$.sentiment_confidence') AS REAL), 0)"
    conditions.append(
        "("
        "json_extract(data, '$.needs_review') = 1"
        f" OR (json_extract(data, '$.sentiment') = 'negative' AND {trust_expr_f} >= 0.5 AND {conf_expr_f} >= 0.6)"
        ")"
    )
    conditions.append("(COALESCE(json_extract(data, '$.human_validated'), 0) = 0)")

    if sentiment:
        conditions.append("json_extract(data, '$.sentiment') = ?")
        params.append(sentiment)

    if range:
        try:
            window_start, window_end, _, _ = _resolve_window(range)
        except Exception:
            window_start = window_end = None
        if window_start and window_end:
            conditions.append(
                "EXISTS (SELECT 1 FROM raw_posts rp "
                "WHERE rp.id = json_extract(analyses.data, '$.post_id') "
                "AND rp.created_timestamp >= ? AND rp.created_timestamp < ?)"
            )
            params.append(window_start.timestamp())
            params.append(window_end.timestamp())

    if macro_subs is not None:
        if not macro_subs:
            return {"queue": [], "total": 0, "offset": offset, "has_more": False}
        placeholders = ",".join(["?"] * len(macro_subs))
        conditions.append(f"LOWER(json_extract(data, '$.subreddit')) IN ({placeholders})")
        params.extend(sorted(macro_subs))

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    # Total count for pagination
    total = _storage._conn.execute(
        f"SELECT COUNT(*) FROM analyses WHERE {where_clause}", params
    ).fetchone()[0]
    # Order by priority tier first (P1 → P2 → other), then by recency, so P1s
    # anywhere in the pool surface before older P2s / others.
    trust_expr = "COALESCE(CAST(json_extract(data, '$.trust_score') AS REAL), 0)"
    conf_expr = "COALESCE(CAST(json_extract(data, '$.sentiment_confidence') AS REAL), 0)"
    tier_rank_sql = (
        f"CASE "
        f"  WHEN {trust_expr} >= 0.7 AND {conf_expr} >= 0.8 THEN 0 "
        f"  WHEN {trust_expr} >= 0.5 AND {conf_expr} >= 0.6 THEN 1 "
        f"  ELSE 2 "
        f"END"
    )
    query = (
        f"SELECT data FROM analyses "
        f"WHERE {where_clause} "
        f"ORDER BY ({tier_rank_sql}) ASC, "
        f"         ({trust_expr} * {conf_expr}) DESC, "
        f"         json_extract(data, '$.analyzed_at') DESC "
        f"LIMIT ? OFFSET ?"
    )
    analyses = _storage.query("analyses", query, params + [limit, offset])

    def _priority_tier(trust: float, conf: float) -> str:
        if trust >= 0.7 and conf >= 0.8:
            return "P1"
        if trust >= 0.5 and conf >= 0.6:
            return "P2"
        return "other"

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

        trust_val = float(item.get("trust_score") or 0.0)
        conf_val = float(item.get("sentiment_confidence") or 0.0)
        tier = _priority_tier(trust_val, conf_val)

        enriched_item = {
            "id": item.get("id", ""),
            "post_id": post_id,
            "sentiment": item.get("sentiment", "unknown"),
            "sentiment_confidence": conf_val,
            "trust_score": trust_val,
            "is_trusted": item.get("is_trusted", False),
            "aspects": item.get("aspects", []),
            "needs_review": item.get("needs_review", True),
            "priority_tier": tier,
            "priority_score": round(trust_val * conf_val, 4),
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

    return {
        "queue": enriched,
        "total": total,
        "offset": offset,
        "has_more": (offset + len(enriched)) < total,
    }


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
        # Aspect override (#5): if the analyst passed a corrected_aspects list,
        # replace the model-inferred aspects. Empty list == "no aspects".
        corrected_aspects = correction.get("corrected_aspects")
        if isinstance(corrected_aspects, list):
            # Store as list of dicts matching the analyzer output shape so the
            # rest of the dashboard doesn't need special-case handling.
            analysis["aspects"] = [
                {"aspect": a, "confidence": 1.0} if isinstance(a, str) else a
                for a in corrected_aspects
            ]
        # Trust override (#6): analyst can force trust to any value in [0, 1].
        trust_override = correction.get("trust_override")
        if trust_override is not None:
            try:
                to_val = max(0.0, min(1.0, float(trust_override)))
                analysis["trust_score"] = to_val
                analysis["trust_override"] = True
            except (TypeError, ValueError):
                pass
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
            aspects_changed=isinstance(corrected_aspects, list),
            trust_changed=trust_override is not None,
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
        "gateway_available": result.get("gateway_available", None),
        "ollama_available": result.get("ollama_available", None),
        "gateway_reason": result.get("gateway_reason", None),
    }


@app.post("/api/review/{post_id}/draft-all")
def draft_all(post_id: str, payload: dict | None = None):
    """Generate both a customer reply draft AND an internal action note in one call.
    Returns the same structure as draft-reply plus an `action_draft` field."""
    _ensure_initialized()
    payload = payload or {}
    subreddit = payload.get("subreddit", "")

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, subreddit)
    if not analysis:
        return {"status": "error", "reason": "analysis_not_found"}

    raw = _storage.get_item("raw_posts", post_id, subreddit) or {}
    aspects = _aspect_names(analysis.get("aspects", []))
    examples = _collect_reply_examples(limit=5)

    # ── Customer reply drafts ──────────────────────────────────────────────────
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
        log.error("draft_all_reply_failed", post_id=post_id, error=str(e))
        return {"status": "error", "reason": str(e)}

    drafts = result.get("drafts", [])

    # ── Internal action note ────────────────────────────────────────────────────
    # Generate from BOTH Walmart LLM Gateway (GPT-4o) AND Mistral (Ollama) in
    # parallel. Return both so the analyst can pick. Falls back to the smart
    # composer template only when both models are unreachable.
    action_drafts: list[dict] = []
    asp = aspects[0] if aspects else "this issue"
    complaint_text = (raw.get('title', '') + ' ' + raw.get('body', '')).strip()[:600]
    action_prompt = (
        "You are a Walmart customer-care operations analyst.\n"
        "Based on this customer complaint, suggest ONE concrete internal action "
        "in 2-3 complete sentences that the ops team should take to prevent this "
        "issue recurring. Name the specific process, system, or team involved.\n\n"
        f"Customer complaint: {complaint_text}\n"
        f"Aspects affected: {', '.join(aspects) or 'general'}\n\n"
        "Internal action recommendation (2-3 complete sentences):"
    )

    def _trim_to_sentence(text: str, cap: int = 600) -> str:
        text = text.strip()
        if len(text) <= cap:
            return text
        last_end = max(text.rfind('. ', 0, cap), text.rfind('! ', 0, cap), text.rfind('? ', 0, cap))
        return text[:last_end + 1] if last_end > 0 else text[:cap]

    try:
        llm2 = _get_reply_llm()

        # ── GPT-4o via Walmart LLM Gateway ─────────────────────────────────────
        try:
            import requests as _req
            url = llm2.config.wmt_gateway_url.rstrip("/") + "/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm2.config.wmt_gateway_key}",
                "WM_CONSUMER.ID": getattr(llm2.config, "wmt_consumer_id", ""),
                "WM_SVC.NAME": getattr(llm2.config, "wmt_svc_name", "isl-ai-engine"),
                "WM_SVC.ENV": getattr(llm2.config, "wmt_svc_env", "stage"),
            }
            resp = _req.post(url, json={
                "model": llm2.config.wmt_gateway_model,
                "messages": [{"role": "user", "content": action_prompt}],
                "temperature": 0.4,
                "max_tokens": 200,
            }, headers=headers, timeout=30, verify=False)
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"].strip()
                if text:
                    action_drafts.append({
                        "model": f"GPT-4o ({llm2.config.wmt_gateway_model})",
                        "source": "gateway",
                        "note": _trim_to_sentence(text),
                    })
                    log.info("action_note_generated", model="gateway_gpt4o")
        except Exception as eg:
            log.warning("action_note_gateway_failed", error=str(eg))

        # ── Mistral via Ollama ─────────────────────────────────────────────────
        if hasattr(llm2, '_ollama_generate_reply'):
            try:
                ollama_text = llm2._ollama_generate_reply(action_prompt)
                if ollama_text:
                    action_drafts.append({
                        "model": f"Mistral ({getattr(llm2.config, 'ollama_model', 'mistral:7b-instruct')})",
                        "source": "ollama",
                        "note": _trim_to_sentence(ollama_text),
                    })
                    log.info("action_note_generated", model="ollama_mistral")
            except Exception as eo:
                log.warning("action_note_ollama_failed", error=str(eo))

        # ── Smart Composer template fallback (only when both LLMs failed) ──────
        if not action_drafts:
            subreddit_val = analysis.get("subreddit", "walmart")
            asp_str = ', '.join(aspects[:2]) if aspects else "general service"
            action_drafts.append({
                "model": "smart-composer",
                "source": "template",
                "note": (
                    f"Escalate to the {asp_str} operations team: review the root cause of "
                    f"this complaint from r/{subreddit_val} and update the relevant SOP within 5 business days. "
                    f"Flag for the weekly customer-feedback triage meeting."
                ),
            })
            log.info("action_note_generated", model="smart_composer_template")

    except Exception as e:
        log.warning("action_draft_failed", post_id=post_id, error=str(e))
        action_drafts.append({
            "model": "template",
            "source": "template",
            "note": f"Review and improve the {asp} process. Escalate to the relevant team for root cause analysis.",
        })

    primary_action = action_drafts[0] if action_drafts else {}

    primary = drafts[0] if drafts else {}
    return {
        "status": "ok",
        "drafts": drafts,
        "reply": primary.get("reply", ""),
        "model_used": primary.get("model_used", ""),
        "source": primary.get("source", ""),
        "examples_used": len(examples),
        "action_draft": primary_action.get("note", ""),
        "action_model": primary_action.get("model", ""),
        "action_drafts": action_drafts,
        "gateway_available": result.get("gateway_available", None),
        "ollama_available": result.get("ollama_available", None),
        "gateway_reason": result.get("gateway_reason", None),
    }


@app.post("/api/review/{post_id}/reply")
def save_reply(post_id: str, payload: dict, request: Request):
    """Persist the analyst-edited reply, then (optionally) post it to Reddit.

    - `reply_text` is always saved to the feedback log + analysis record.
    - If `payload["post_to_reddit"]` is truthy, we also call the Reddit poster
      using the current session's token. With `reddit_oauth.dry_run=True`
      (default), the poster just logs the intent — the dashboard surfaces
      `posted` / `dry_run` / `rate_limited` distinctly.
    """
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

    response: dict = {"status": "saved", "feedback_id": fb["id"], "reply_posted_at": now}

    # Auto-transition into lifecycle "reply_sent" state when a reply is saved.
    _ensure_lifecycle_reply_sent(post_id, analysis, now)

    # Optional second leg: actually post to Reddit. We treat this as best-effort
    # — the local audit log save above is the source of truth.
    if payload.get("post_to_reddit"):
        from src.reddit.poster import post_reply as reddit_post_reply
        cfg = _config.reddit_oauth
        bundle = _current_reddit_token(request)
        access_token = bundle.access_token if (bundle and not cfg.dry_run) else None
        username = bundle.username if bundle else None
        result = reddit_post_reply(
            post_id=post_id,
            reply_text=reply_text,
            cfg=cfg,
            access_token=access_token,
            username=username,
        )
        response["reddit"] = result
        if result.get("ok") and not result.get("dry_run") and result.get("posted_id") and analysis:
            analysis["reddit_posted_id"] = result["posted_id"]
            _storage.upsert("analyses", analysis)

    return response


def _needs_follow_up(post_id: str, analysis: dict, threshold_days: int = 3) -> bool:
    """Return True when a reply was sent 3+ days ago but lifecycle is still reply_sent."""
    reply_at = analysis.get("reply_posted_at")
    if not reply_at:
        return False
    try:
        sent = datetime.fromisoformat(reply_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - sent).days
        if age_days < threshold_days:
            return False
        lc = _storage.lifecycle_get(post_id)
        return bool(lc and lc.get("state") == "reply_sent")
    except Exception:
        return False


@app.get("/api/review/reviewed")
def get_reviewed(
    limit: int = Query(50, ge=1, le=200),
    sentiment: str = Query(None),
    range: str = Query(None, alias="range"),
    macro_segment: str = Query(None, description="Optional macro group: 'walmart' or 'competitor'."),
):
    """Return posts that have already been human-validated (left the review queue)."""
    _ensure_initialized()
    conditions = ["json_extract(data, '$.human_validated') = 1"]
    params: list = []
    if sentiment:
        conditions.append("json_extract(data, '$.sentiment') = ?")
        params.append(sentiment)
    if range:
        cutoff = _range_to_cutoff(range)
        if cutoff:
            conditions.append("json_extract(data, '$.analyzed_at') >= ?")
            params.append(cutoff)
    if macro_segment:
        try:
            from src.utils.segments import _load_macro_map
            macro_subs2 = {s for s, m in _load_macro_map().items() if m == macro_segment}
            if not macro_subs2:
                return {"queue": [], "total": 0}
            placeholders = ",".join(["?"] * len(macro_subs2))
            conditions.append(f"LOWER(json_extract(data, '$.subreddit')) IN ({placeholders})")
            params.extend(sorted(macro_subs2))
        except Exception:
            pass
    params.append(limit)
    query = (
        f"SELECT data FROM analyses WHERE {' AND '.join(conditions)} "
        f"ORDER BY json_extract(data, '$.validated_at') DESC LIMIT ?"
    )
    analyses = _storage.query("analyses", query, params)
    enriched = []
    for item in analyses:
        post_id = item.get("post_id", "")
        post = _storage.get_item("raw_posts", post_id, item.get("subreddit", ""))
        reddit_url = ""
        if post and post.get("url"):
            reddit_url = post["url"]
        elif post_id.startswith("reddit_"):
            bare = post_id[len("reddit_"):]
            reddit_url = f"https://www.reddit.com/r/{item.get('subreddit', '')}/comments/{bare}/"
        enriched.append({
            "id": item.get("id", ""),
            "post_id": post_id,
            "sentiment": item.get("sentiment", "unknown"),
            "sentiment_confidence": item.get("sentiment_confidence", 0),
            "trust_score": item.get("trust_score", 0),
            "aspects": item.get("aspects", []),
            "needs_review": False,
            "subreddit": item.get("subreddit", ""),
            "analyzed_at": item.get("analyzed_at", ""),
            "validated_at": item.get("validated_at", ""),
            "validated_by": item.get("validated_by", ""),
            "close_reason": item.get("close_reason", ""),
            "model": item.get("model_used", ""),
            "text": post.get("body", post.get("title", "")) if post else "",
            "title": post.get("title", "") if post else "",
            "author": post.get("author", "") if post else "",
            "score": post.get("score", 0) if post else 0,
            "created_timestamp": post.get("created_timestamp", 0) if post else 0,
            "reddit_url": reddit_url,
            "can_generate_reply": item.get("sentiment") == "negative",
            "reply_posted_at": item.get("reply_posted_at"),
            "reply_text": item.get("reply_text", ""),
            # Follow-up flag: reply was sent 3+ days ago but lifecycle not resolved
            "follow_up_needed": _needs_follow_up(post_id, item),
        })
    return {"queue": enriched, "total": len(enriched)}


@app.post("/api/review/{post_id}/confirm")
def confirm_review(post_id: str, payload: dict | None = None):
    """Record a human confirmation of the model's sentiment label.
    Moves the post out of the review queue (needs_review=False) and into Reviewed tab."""
    _ensure_initialized()
    payload = payload or {}
    now = datetime.now(timezone.utc).isoformat()
    subreddit = payload.get("subreddit", "")

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, subreddit)
    if not analysis:
        return {"status": "error", "reason": "analysis_not_found"}

    sentiment = analysis.get("sentiment", "neutral")

    # Mark as reviewed (same as a correction that agrees with the model)
    analysis["needs_review"] = False
    analysis["human_validated"] = True
    analysis["validated_at"] = now
    analysis["validated_by"] = payload.get("analyst_id", "default")
    _storage.upsert("analyses", analysis)

    _storage.upsert("feedback", {
        "id": f"confirm_{post_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "post_id": post_id,
        "analyst_id": payload.get("analyst_id", "default"),
        "kind": "confirmation",
        "original_sentiment": sentiment,
        "corrected_sentiment": sentiment,  # same — counts as agreement in accuracy tracker
        "notes": "Human confirmed model label",
        "created_at": now,
        "partition_key": payload.get("analyst_id", "default"),
    })
    log.info("review_confirmed", post_id=post_id, sentiment=sentiment)
    return {"status": "confirmed", "post_id": post_id}


@app.post("/api/review/{post_id}/close")
def close_review(post_id: str, payload: dict | None = None):
    """Close a review with one of three lifecycle paths:
      close_type='no_reply'    → resolved (no action taken)
      close_type='issue_fixed' → issue_fixed (action identified, reply was sent)
      close_type='reply_sent'  → reply_sent (monitoring, reply was sent, no action yet)
    """
    _ensure_initialized()
    payload = payload or {}
    now = datetime.now(timezone.utc).isoformat()
    subreddit = payload.get("subreddit", "")
    close_type = payload.get("close_type", "no_reply")  # no_reply | issue_fixed | reply_sent
    action_note = payload.get("action_note", "")  # GPT-generated action for issue_fixed

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, subreddit)
    if not analysis:
        return {"status": "error", "reason": "analysis_not_found"}

    analysis["needs_review"] = False
    analysis["human_validated"] = True
    analysis["validated_at"] = now
    analysis["validated_by"] = payload.get("analyst_id", "default")
    analysis["close_reason"] = close_type
    if action_note:
        analysis["action_note"] = action_note
    _storage.upsert("analyses", analysis)

    _storage.upsert("feedback", {
        "id": f"close_{post_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "post_id": post_id,
        "analyst_id": payload.get("analyst_id", "default"),
        "kind": f"closed_{close_type}",
        "close_reason": close_type,
        "action_note": action_note,
        "created_at": now,
        "partition_key": payload.get("analyst_id", "default"),
    })

    # Map close_type to lifecycle state
    target_state = {
        "no_reply":    "resolved",
        "issue_fixed": "issue_fixed",
        "reply_sent":  "reply_sent",
    }.get(close_type, "resolved")

    try:
        existing = _storage.lifecycle_get(post_id)
        if existing:
            existing["state"] = target_state
            existing["updated_at"] = now
            if action_note:
                existing["action_note"] = action_note
            _storage.lifecycle_upsert(existing)
        else:
            raw = _storage.get_item("raw_posts", post_id, subreddit)
            _storage.lifecycle_upsert({
                "id": f"lc_{post_id}",
                "post_id": post_id,
                "state": target_state,
                "priority": "medium" if close_type == "issue_fixed" else "low",
                "subreddit": subreddit,
                "title": (raw or {}).get("title", ""),
                "top_aspect": "",
                "action_note": action_note,
                "sentiment_score": analysis.get("sentiment_confidence", 0),
                "sentiment_confidence": analysis.get("sentiment_confidence", 0),
                "created_at": now,
                "updated_at": now,
            })
    except Exception as e:
        log.warning("close_lifecycle_update_failed", post_id=post_id, error=str(e))

    log.info("review_closed", post_id=post_id, close_type=close_type)
    return {"status": "closed", "post_id": post_id, "lifecycle_state": target_state}


@app.post("/api/review/{post_id}/generate-action")
def generate_action(post_id: str, payload: dict | None = None):
    """Use the LLM to draft a short recommended action for a post that had a
    reply sent. The action is shown in the Lifecycle 'Actionable Items' column."""
    _ensure_initialized()
    payload = payload or {}
    subreddit = payload.get("subreddit", "")

    analysis_id = f"analysis_{post_id}"
    analysis = _storage.get_item("analyses", analysis_id, subreddit)
    if not analysis:
        return {"status": "error", "reason": "analysis_not_found"}

    raw = _storage.get_item("raw_posts", post_id, subreddit) or {}
    aspects = _aspect_names(analysis.get("aspects", []))
    reply_text = analysis.get("reply_text", "")

    prompt = (
        "You are a Walmart customer-care operations analyst.\n"
        "A customer posted a complaint and an analyst sent a reply.\n"
        "Based on the complaint and the reply, suggest ONE concrete internal action "
        "(1-2 sentences max) that the ops team should take to prevent this issue in future.\n"
        "Be specific — name the process, system, or team involved.\n\n"
        f"Customer complaint: {(raw.get('title','') + ' ' + raw.get('body','')).strip()[:800]}\n"
        f"Aspects: {', '.join(aspects) or 'general'}\n"
        f"Reply sent: {reply_text[:400]}\n\n"
        "Recommended action:"
    )

    try:
        llm = _get_reply_llm()
        # Reuse gateway infrastructure — call _gateway_generate_reply if available
        if hasattr(llm, '_gateway_generate_reply'):
            action = llm._gateway_generate_reply(prompt)
            if not action or action == "__consumer_id_error__":
                raise ValueError("gateway unavailable")
        else:
            result = llm.generate_reply(
                raw.get("title", ""), raw.get("body", "") or raw.get("title", ""),
                subreddit, raw.get("author", ""), aspects,
            )
            action = result.get("reply", "")
        action = action.strip()[:400]
        log.info("action_generated", post_id=post_id, length=len(action))
        return {"status": "ok", "action": action}
    except Exception as e:
        log.warning("action_generation_failed", post_id=post_id, error=str(e))
        return {"status": "ok", "action": ""}  # graceful fallback — analyst enters manually


@app.get("/api/review/stats")
def review_stats():
    """Counts of how many corrections have been applied — proof that the
    feedback loop is working. Used for the 'LLM is learning' indicator and the
    Model Accuracy Tracker chart.

    Returns:
        total_feedback       — every feedback row (corrections + replies)
        total_reviewed       — reviews with both original + corrected sentiment
        total_corrections    — reviews where corrected != original (model was wrong)
        total_confirmations  — reviews where corrected == original (model was right)
        total_replies_posted — analyst-posted reply count
        agreement_rate       — confirmations / total_reviewed (0..1)
        correction_matrix    — dict of "from->to": count
        daily_accuracy       — [{date, reviewed, confirmed, agreement_rate}] for chart
    """
    _ensure_initialized()
    rows = _storage.query("feedback", "SELECT data FROM feedback", [])
    reviewed = [
        r for r in rows
        if r.get("corrected_sentiment") and r.get("original_sentiment")
    ]
    corrections = [r for r in reviewed if r["corrected_sentiment"] != r["original_sentiment"]]
    confirmations = [r for r in reviewed if r["corrected_sentiment"] == r["original_sentiment"]]
    by_pair: Counter = Counter()
    for r in corrections:
        by_pair[(r["original_sentiment"], r["corrected_sentiment"])] += 1
    replies = [r for r in rows if r.get("kind") == "auto_reply_posted"]

    # Daily accuracy time-series for the tracker chart (#4).
    # Bucket every review row by its calendar date (UTC) and compute the
    # confirmation rate. This is what the model would have gotten right had
    # the analyst not been in the loop.
    daily: dict[str, dict] = {}
    for r in reviewed:
        ts = r.get("created_at", "")[:10]  # YYYY-MM-DD prefix
        if not ts:
            continue
        d = daily.setdefault(ts, {"reviewed": 0, "confirmed": 0})
        d["reviewed"] += 1
        if r["corrected_sentiment"] == r["original_sentiment"]:
            d["confirmed"] += 1
    daily_accuracy = [
        {
            "date": date,
            "reviewed": v["reviewed"],
            "confirmed": v["confirmed"],
            "agreement_rate": round(v["confirmed"] / v["reviewed"], 4) if v["reviewed"] else 0.0,
        }
        for date, v in sorted(daily.items())
    ]

    total_reviewed = len(reviewed)
    agreement_rate = round(len(confirmations) / total_reviewed, 4) if total_reviewed else 0.0

    return {
        "total_feedback": len(rows),
        "total_reviewed": total_reviewed,
        "total_corrections": len(corrections),
        "total_confirmations": len(confirmations),
        "total_replies_posted": len(replies),
        "agreement_rate": agreement_rate,
        "correction_matrix": {f"{k[0]}->{k[1]}": v for k, v in by_pair.items()},
        "daily_accuracy": daily_accuracy,
    }


@app.get("/api/review/feedback-history")
def feedback_history(limit: int = Query(50, ge=1, le=500)):
    """Full audit log of past corrections (most recent first). Powers the
    Feedback History table on the Review page (#7).

    Each row includes the post id, original and corrected labels, aspects that
    changed, any trust override, and the analyst who did it.
    """
    _ensure_initialized()
    rows = _storage.query("feedback", "SELECT data FROM feedback", [])
    # Only include actual review corrections, skip auto-reply logs.
    reviewed = [
        r for r in rows
        if r.get("corrected_sentiment") and r.get("original_sentiment")
    ]
    # Sort by created_at descending; feedback rows without a timestamp bubble down.
    reviewed.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    reviewed = reviewed[:limit]

    def _aspect_diff(before: list, after: list) -> list[str]:
        b = set(_aspect_names(before))
        a = set(_aspect_names(after))
        return sorted(list((b - a) | (a - b)))

    return {
        "items": [
            {
                "id": r.get("id"),
                "post_id": r.get("post_id"),
                "analyst_id": r.get("analyst_id", "default"),
                "original_sentiment": r.get("original_sentiment"),
                "corrected_sentiment": r.get("corrected_sentiment"),
                "changed": r.get("corrected_sentiment") != r.get("original_sentiment"),
                "aspects_changed": _aspect_diff(r.get("original_aspects", []), r.get("corrected_aspects", [])),
                "trust_override": r.get("trust_override"),
                "notes": r.get("notes", ""),
                "created_at": r.get("created_at"),
            }
            for r in reviewed
        ],
        "total": len(reviewed),
    }



# ─── P1: Alert Feed ────────────────────────────────────────────────────────────

@app.get("/api/alerts")
def get_alerts(
    range: str = Query("week", description="Time window filter on detected_at (ISO). Default: week."),
    severity: str | None = Query(None, description="Optional filter: high | medium | low"),
    alert_type: str | None = Query(None, alias="type", description="Optional filter: volume_spike | sentiment_crash | emerging_topic | competitor_negative"),
    state: str | None = Query(None, description="Optional filter: new | acknowledged | investigating | resolved"),
    live: bool = Query(False, description="If true, run detectors right now instead of reading stored alerts."),
    limit: int = Query(100, ge=1, le=1000),
):
    """Alerts feed. Reads from the `alerts` table by default (populated by
    every pipeline cycle) so history is preserved. Filters by `detected_at`
    matching the requested range; supports optional severity, type, and
    workflow-state filters.

    Set `live=true` to bypass storage and re-run the detectors against
    current aggregates — useful for on-demand "check now" without waiting
    for the next scheduled cycle.
    """
    _ensure_initialized()
    if live:
        alerts = _alert_engine.detect_all()
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        if alert_type:
            alerts = [a for a in alerts if a.get("type") == alert_type]
        return {"alerts": alerts[:limit], "count": len(alerts[:limit]), "total": len(alerts), "source": "live"}

    if range not in _VALID_RANGES:
        return {"alerts": [], "count": 0, "error": f"Invalid range. Valid: {_VALID_RANGES}"}

    # Compute the ISO cutoff so we can filter on detected_at (ISO 8601 string).
    now = datetime.now(timezone.utc)
    if range in _HOUR_RANGES:
        cutoff_dt = now - timedelta(hours=_HOUR_RANGES[range])
    else:
        offset_days, days_back = _DAY_RANGES[range]
        if days_back == 1:
            cutoff_dt = (now - timedelta(days=offset_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff_dt = now - timedelta(days=days_back)
    cutoff_iso = cutoff_dt.isoformat()

    where = ["json_extract(data, '$.detected_at') >= ?"]
    params: list = [cutoff_iso]
    if severity:
        where.append("json_extract(data, '$.severity') = ?")
        params.append(severity)
    if alert_type:
        where.append("json_extract(data, '$.type') = ?")
        params.append(alert_type)
    if state:
        # Alerts without an explicit state count as "new" for filtering.
        if state == "new":
            where.append("COALESCE(json_extract(data, '$.state'), 'new') = 'new'")
        else:
            where.append("json_extract(data, '$.state') = ?")
            params.append(state)
    where_sql = " AND ".join(where)

    try:
        # Count first (for `total`), then fetch the page.
        total = _storage._conn.execute(  # type: ignore[attr-defined]
            f"SELECT COUNT(*) FROM alerts WHERE {where_sql}", params
        ).fetchone()[0]
        rows = _storage._conn.execute(  # type: ignore[attr-defined]
            f"SELECT data FROM alerts WHERE {where_sql} "
            "ORDER BY json_extract(data, '$.detected_at') DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        log.error("alerts_query_failed", error=str(e))
        return {"alerts": [], "count": 0, "error": str(e)}

    import json as _json
    alerts = [_json.loads(r["data"]) for r in rows]

    # Backward-compat enrichment: older sentiment_crash rows may not include
    # affected group details. Compute current context and patch matching rows
    # in-memory so the UI can show actionable ownership immediately.
    sentiment_ctx: dict | None = None
    try:
        live_ctx = _alert_engine.detect_sentiment_crash(drop_threshold=-1.0)
        if live_ctx:
            sentiment_ctx = live_ctx[0]
    except Exception:
        sentiment_ctx = None

    top_sub_cache: dict[str, str] = {}

    def _top_subs_for_macro_day(macro: str, day_key: str) -> str:
        cache_key = f"{macro}|{day_key}"
        if cache_key in top_sub_cache:
            return top_sub_cache[cache_key]
        try:
            try:
                day_start_dt = datetime.fromisoformat(day_key).replace(tzinfo=timezone.utc)
            except Exception:
                day_start_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            next_day_dt = day_start_dt + timedelta(days=1)
            day_start_ts = day_start_dt.timestamp()
            next_day_ts = next_day_dt.timestamp()
            rows2 = _storage._conn.execute(  # type: ignore[attr-defined]
                "SELECT a.data AS adata, r.subreddit AS sub "
                "FROM analyses a JOIN raw_posts r ON a.post_id = r.id "
                "WHERE r.created_timestamp >= ? AND r.created_timestamp < ?",
                [day_start_ts, next_day_ts],
            ).fetchall()
            import json as _j
            stats: dict[str, dict[str, int]] = {}
            for rr in rows2:
                sub = (rr["sub"] or "").strip().lower()
                if not sub or macro_segment_for(sub) != macro:
                    continue
                d = _j.loads(rr["adata"])
                st = stats.setdefault(sub, {"neg": 0, "total": 0})
                st["total"] += 1
                if d.get("sentiment") == "negative":
                    st["neg"] += 1
            ranked = []
            for sub, st in stats.items():
                if st["total"] <= 0:
                    continue
                ratio = st["neg"] / st["total"]
                ranked.append((ratio, st["neg"], st["total"], sub))
            ranked.sort(reverse=True)
            out = " | ".join([f"r/{s} ({n}/{t}, {r:.0%})" for r, n, t, s in ranked[:3]])

            # Fallback: if we have no analysed rows yet for this day window,
            # show top subreddits by raw post volume so the owner is visible.
            if not out:
                rows3 = _storage._conn.execute(  # type: ignore[attr-defined]
                    "SELECT subreddit AS sub, COUNT(*) AS n FROM raw_posts "
                    "WHERE created_timestamp >= ? AND created_timestamp < ? "
                    "GROUP BY subreddit ORDER BY n DESC LIMIT 100",
                    [day_start_ts, next_day_ts],
                ).fetchall()
                tops = []
                for rr in rows3:
                    sub2 = (rr["sub"] or "").strip().lower()
                    if not sub2 or macro_segment_for(sub2) != macro:
                        continue
                    tops.append((int(rr["n"] or 0), sub2))
                    if len(tops) >= 3:
                        break
                out = " | ".join([f"r/{s} ({n} posts)" for n, s in tops])

            # Second fallback: if that day has no rows at all, use previous day.
            if not out:
                prev_start = day_start_ts - 86400
                prev_end = day_start_ts
                rows4 = _storage._conn.execute(  # type: ignore[attr-defined]
                    "SELECT subreddit AS sub, COUNT(*) AS n FROM raw_posts "
                    "WHERE created_timestamp >= ? AND created_timestamp < ? "
                    "GROUP BY subreddit ORDER BY n DESC LIMIT 100",
                    [prev_start, prev_end],
                ).fetchall()
                tops2 = []
                for rr in rows4:
                    sub3 = (rr["sub"] or "").strip().lower()
                    if not sub3 or macro_segment_for(sub3) != macro:
                        continue
                    tops2.append((int(rr["n"] or 0), sub3))
                    if len(tops2) >= 3:
                        break
                out = " | ".join([f"r/{s} ({n} posts, prev day)" for n, s in tops2])
            top_sub_cache[cache_key] = out
            return out
        except Exception:
            top_sub_cache[cache_key] = ""
            return ""

    # Normalise state field so the UI never has to deal with missing keys.
    for a in alerts:
        if a.get("type") == "sentiment_crash":
            details = a.setdefault("details", {})
            if sentiment_ctx and a.get("id") == sentiment_ctx.get("id"):
                ctx_details = sentiment_ctx.get("details", {}) or {}
                for k in (
                    "affected_macro_group",
                    "affected_macro_delta",
                    "competitor_delta",
                    "walmart_delta",
                    "top_subreddits_today",
                ):
                    if k not in details and k in ctx_details:
                        details[k] = ctx_details[k]
                # Ensure title also carries the group label for older rows.
                grp = details.get("affected_macro_group")
                if grp and "(" not in (a.get("title") or ""):
                    label = "Competitors" if grp == "competitor" else "Walmart"
                    base = a.get("title") or "Sentiment crash"
                    if base.startswith("Sentiment crash"):
                        base = base.replace("Sentiment crash", f"Sentiment crash ({label})", 1)
                    else:
                        base = f"Sentiment crash ({label}): {base}"
                    a["title"] = base

            # If we have subgroup context but title is generic, append top
            # subreddit so the owner is obvious from the card headline.
            tsubs = str(details.get("top_subreddits_today") or "")
            if not tsubs:
                grp0 = str(details.get("affected_macro_group") or "").strip().lower()
                if not grp0:
                    title0 = str(a.get("title") or "")
                    if "(Competitors" in title0:
                        grp0 = "competitor"
                    elif "(Walmart" in title0:
                        grp0 = "walmart"
                if grp0 in ("walmart", "competitor"):
                    day_key = str(a.get("time_window") or "")
                    tsubs = _top_subs_for_macro_day(grp0, day_key)
                    if tsubs:
                        details["top_subreddits_today"] = tsubs
            if tsubs and "r/" not in (a.get("title") or ""):
                if " | " in tsubs:
                    first = tsubs.split(" | ")[0].strip()
                elif "), " in tsubs:
                    first = tsubs.split("), ")[0].strip() + ")"
                else:
                    first = tsubs.split(",")[0].strip()
                if first:
                    a["title"] = f"{a.get('title') or 'Sentiment crash'} [{first}]"
        a.setdefault("state", "new")
    return {"alerts": alerts, "count": len(alerts), "total": total, "source": "stored", "range": range}


# ─── Alert workflow: state transitions + timeline + rules ─────────────────────

_VALID_ALERT_STATES = {"new", "acknowledged", "investigating", "resolved"}


@app.post("/api/alerts/{alert_id}/state")
def update_alert_state(alert_id: str, payload: dict):
    """Transition an alert to a new workflow state (acknowledged / investigating / resolved).

    Adds `state`, `state_updated_at`, `state_updated_by`, and appends the
    transition to a `state_history` list so we keep a full audit trail on
    the alert record itself.
    """
    _ensure_initialized()
    new_state = (payload.get("state") or "").strip().lower()
    if new_state not in _VALID_ALERT_STATES:
        return {"status": "error", "reason": f"invalid state; expected one of {sorted(_VALID_ALERT_STATES)}"}

    import json as _json
    try:
        row = _storage._conn.execute(  # type: ignore[attr-defined]
            "SELECT data FROM alerts WHERE id = ? LIMIT 1", [alert_id]
        ).fetchone()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": str(e)}
    if not row:
        return {"status": "error", "reason": "alert_not_found"}

    alert = _json.loads(row["data"])
    now_iso = datetime.now(timezone.utc).isoformat()
    prev_state = alert.get("state", "new")
    who = (payload.get("analyst_id") or "default").strip()
    note = (payload.get("note") or "").strip()

    alert["state"] = new_state
    alert["state_updated_at"] = now_iso
    alert["state_updated_by"] = who
    history = alert.setdefault("state_history", [])
    history.append({
        "from": prev_state,
        "to": new_state,
        "at": now_iso,
        "by": who,
        "note": note,
    })
    _storage.upsert("alerts", alert)
    log.info("alert_state_updated", alert_id=alert_id, from_state=prev_state, to_state=new_state, by=who)
    return {"status": "saved", "alert": alert}


@app.get("/api/alerts/timeline")
def alerts_timeline(days: int = Query(30, ge=1, le=90)):
    """Daily alert counts for the last N days, broken down by severity.
    Powers the Alert Feed timeline chart.
    """
    _ensure_initialized()
    import json as _json
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_iso = start.isoformat()

    try:
        rows = _storage._conn.execute(  # type: ignore[attr-defined]
            "SELECT data FROM alerts WHERE json_extract(data, '$.detected_at') >= ?",
            [cutoff_iso],
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        return {"buckets": [], "error": str(e)}

    day_keys = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    buckets = {d: {"date": d, "high": 0, "medium": 0, "low": 0, "total": 0} for d in day_keys}
    for r in rows:
        try:
            a = _json.loads(r["data"])
        except Exception:
            continue
        det = a.get("detected_at", "")[:10]
        if det not in buckets:
            continue
        sev = a.get("severity", "low")
        if sev not in ("high", "medium", "low"):
            sev = "low"
        buckets[det][sev] += 1
        buckets[det]["total"] += 1
    return {"buckets": [buckets[d] for d in day_keys]}


# ─── Alert rules (thresholds) ────────────────────────────────────────────────
# Persisted to disk as a tiny JSON file so demo edits survive restarts. When
# empty the alert engine falls back to its hard-coded defaults.

_ALERT_RULES_PATH = "data/alert_rules.json"

_DEFAULT_ALERT_RULES = {
    "volume_spike": {
        "enabled": True,
        "sigma_threshold": 2.0,
        "description": "Alert when today's post count exceeds N sigma above the 7-day mean.",
    },
    "sentiment_crash": {
        "enabled": True,
        "drop_threshold": 0.3,
        "description": "Alert when negative-sentiment ratio jumps by this much vs yesterday.",
    },
    "emerging_topic": {
        "enabled": True,
        "min_posts": 5,
        "window_hours": 2,
        "description": "Alert when a new phrase cluster appears (>= N posts in the window).",
    },
    "competitor_negative": {
        "enabled": True,
        "delta_threshold": 0.15,
        "min_posts_per_window": 25,
        "description": "Alert when a competitor subreddit's negative ratio jumps by at least this amount week-over-week.",
    },
}


def _load_alert_rules() -> dict:
    import json as _json
    from pathlib import Path
    p = Path(_ALERT_RULES_PATH)
    if not p.exists():
        return dict(_DEFAULT_ALERT_RULES)
    try:
        data = _json.loads(p.read_text())
        # Merge saved values over defaults so newly-added rule types show up.
        merged = {k: dict(v) for k, v in _DEFAULT_ALERT_RULES.items()}
        for k, v in (data or {}).items():
            if k in merged and isinstance(v, dict):
                merged[k].update(v)
        return merged
    except Exception as e:  # noqa: BLE001
        log.warning("alert_rules_load_failed", error=str(e))
        return dict(_DEFAULT_ALERT_RULES)


def _save_alert_rules(rules: dict) -> None:
    import json as _json
    from pathlib import Path
    p = Path(_ALERT_RULES_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(rules, indent=2))


@app.get("/api/alerts/rules")
def get_alert_rules():
    """Return the current user-editable thresholds. Falls back to defaults
    when nothing has been saved yet.
    """
    _ensure_initialized()
    return {"rules": _load_alert_rules()}


@app.post("/api/alerts/rules")
def update_alert_rules(payload: dict):
    """Save updated thresholds. Body: {rules: {rule_key: {field: value, ...}}}
    Only fields present in the default schema are applied; unknown keys are
    ignored so a malformed request can't corrupt the store.
    """
    _ensure_initialized()
    incoming = payload.get("rules") or {}
    current = _load_alert_rules()
    for rule_key, updates in incoming.items():
        if rule_key not in current or not isinstance(updates, dict):
            continue
        for field, value in updates.items():
            if field in current[rule_key]:
                current[rule_key][field] = value
    _save_alert_rules(current)
    log.info("alert_rules_updated", changed=list(incoming.keys()))
    return {"status": "saved", "rules": current}


# ─── P1: Post Explorer ─────────────────────────────────────────────────────────

@app.get("/api/posts")
def search_posts(
    subreddit: str = Query(None),
    sentiment: str = Query(None),
    aspect: str = Query(None),
    segment: str = Query(None, description="Optional segment slug to filter by (see /api/segments)."),
    macro_segment: str = Query(None, description="Optional macro group: 'walmart' or 'competitor'."),
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
    if macro_segment:
        if macro_segment not in MACRO_GROUPS:
            return {"posts": [], "count": 0, "error": f"invalid macro_segment '{macro_segment}'"}
        # Build the subreddit IN-list for this macro group from the registry.
        from src.ingestion.subreddit_registry import load_all as _load_all_registry
        macro_subs = [e.subreddit for e in _load_all_registry() if e.macro_group == macro_segment]
        if not macro_subs:
            return {"posts": [], "count": 0}
        placeholders = ",".join(["?"] * len(macro_subs))
        where.append(f"a.subreddit IN ({placeholders})")
        params.extend(macro_subs)
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
            "macro_segment": macro_segment_for(a.get("subreddit", "") or p.get("subreddit", "")),
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
            # Vision output: caption from Ollama gemma3:4b and the source
            # image URL so the UI can render both together.
            "image_caption": p.get("image_caption", ""),
            "image_url": p.get("thumbnail") or p.get("url_overridden_by_dest") or p.get("preview_url") or "",
        })

    # `count` is the returned page size (always == len(out)); `total` is the
    # true number of rows matching the filters in the window. Callers can
    # show "Showing 50 of 5,234" without a second network round-trip.
    total_matching = len(out)
    try:
        count_sql = (
            "SELECT COUNT(*) FROM analyses a "
            "LEFT JOIN raw_posts p ON p.id = a.post_id "
            f"{where_sql}"
        )
        # Params minus the trailing LIMIT that only applied to the sample.
        total_matching = _storage._conn.execute(count_sql, params[:-1]).fetchone()[0]  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        log.warning("posts_count_failed", error=str(e))

    return {"posts": out, "count": len(out), "total": total_matching, "trust_gate": _trust_gate_info()}


# ─── P2: Trust Analytics ───────────────────────────────────────────────────────

@app.get("/api/trust-stats")
def get_trust_stats(limit: int = Query(2000, ge=100, le=10000), examples: int = Query(15, ge=0, le=100)):
    """Trust filter analytics: distribution, filter rate, flag breakdown,
    component averages, and low-trust examples for the Trust Analytics page.

    Args:
        limit: how many recent raw_posts to sample (default 2000, max 10000).
        examples: how many low-trust example posts to return for the analyst
                  review table (default 15).
    """
    _ensure_initialized()
    query = f"SELECT data FROM raw_posts ORDER BY created_timestamp DESC LIMIT {int(limit)}"
    raw_recent = _storage.query("raw_posts", query, [])

    # Only include posts that already have a real trust_score — ignore unscored
    # raw_posts so metrics match the historical Trust Analytics behavior.
    def _has_score(post: dict) -> bool:
        raw = post.get("trust_score")
        if raw is None:
            return False
        try:
            float(raw)
        except (TypeError, ValueError):
            return False
        return True

    recent = [p for p in raw_recent if _has_score(p)]

    if not recent:
        return {
            "total": 0, "trusted": 0, "flagged": 0, "trust_rate": 0.0,
            "distribution": {}, "flag_breakdown": {}, "component_avg": {},
            "low_trust_examples": [], "threshold": _config.trust.threshold,
        }

    def _trust_score(post: dict) -> float:
        return float(post.get("trust_score") or 0.0)

    threshold = _config.trust.threshold
    trusted_posts = [p for p in recent if _trust_score(p) >= threshold]
    flagged_posts = [p for p in recent if _trust_score(p) < threshold]

    # Distribution histogram (5 buckets, 0.2 wide).
    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for p in recent:
        score = _trust_score(p)
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

    # Flag breakdown — reasons the LLM credibility check flagged posts as low
    # quality (e.g. "new_account", "repeated_text", "spam_pattern"). Each post
    # can have 0..N flags. Missing → counted as "no_flags".
    flag_counter: Counter = Counter()
    for p in flagged_posts:
        flags = p.get("trust_flags") or []
        if not flags:
            flag_counter["no_llm_flags"] += 1
        else:
            for f in flags:
                flag_counter[str(f)] += 1

    # Component averages across the sample — shows which sub-scorer is
    # driving trust the most. Uses `trust_components` written by scorer.py.
    comp_sum = {"metadata": 0.0, "dedup": 0.0, "llm": 0.0}
    comp_count = 0
    for p in recent:
        comps = p.get("trust_components") or {}
        if not comps:
            continue
        comp_count += 1
        for k in comp_sum:
            v = comps.get(k)
            if isinstance(v, (int, float)):
                comp_sum[k] += float(v)
    component_avg = (
        {k: round(v / comp_count, 3) for k, v in comp_sum.items()}
        if comp_count else {k: None for k in comp_sum}
    )

    # Low-trust examples for the analyst review table.
    flagged_sorted = sorted(flagged_posts, key=_trust_score)
    examples_out = []
    for p in flagged_sorted[:examples]:
        text = (p.get("body") or p.get("title") or "").strip()
        if len(text) > 240:
            text = text[:237] + "…"
        examples_out.append({
            "id": p.get("id"),
            "subreddit": p.get("subreddit"),
            "author": p.get("author"),
            "title": p.get("title"),
            "text": text,
            "trust_score": _trust_score(p),
            "trust_components": p.get("trust_components", {}),
            "trust_flags": p.get("trust_flags", []),
            "score": p.get("score", 0),
            "url": p.get("url", ""),
            "created_timestamp": p.get("created_timestamp"),
        })

    return {
        "total": len(recent),
        "trusted": len(trusted_posts),
        "flagged": len(flagged_posts),
        "trust_rate": round(len(trusted_posts) / max(len(recent), 1), 3),
        "distribution": buckets,
        "flag_breakdown": dict(flag_counter.most_common()),
        "component_avg": component_avg,
        "low_trust_examples": examples_out,
        "threshold": threshold,
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


# ─── Notification Groups CRUD ─────────────────────────────────────────────────

NOTIFICATION_SENDER = "vishal.singh1@walmart.com"


@app.get("/api/notifications/config")
async def get_notification_config():
    """Return global notification config + all groups."""
    groups = _storage.notification_groups_list()
    return {
        "sender_email": NOTIFICATION_SENDER,
        "groups": groups,
    }


@app.get("/api/notifications/groups")
async def list_notification_groups():
    return {"groups": _storage.notification_groups_list()}


@app.get("/api/notifications/groups/{group_id}")
async def get_notification_group(group_id: str):
    g = _storage.notification_group_get(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


@app.post("/api/notifications/groups")
async def create_notification_group(req: Request):
    body = await req.json()
    import uuid
    group_id = body.get("id") or str(uuid.uuid4())[:8]
    group = {
        "id": group_id,
        "group_name": body.get("group_name", "Unnamed Group"),
        "subreddits": body.get("subreddits", []),
        "email_dl": body.get("email_dl", []),
        "slack_channel": body.get("slack_channel", ""),
        "enabled": body.get("enabled", True),
        "priority_filter": body.get("priority_filter", ["P1", "P2"]),
    }
    _storage.notification_group_upsert(group)
    return {"ok": True, "group": _storage.notification_group_get(group_id)}


@app.put("/api/notifications/groups/{group_id}")
async def update_notification_group(group_id: str, req: Request):
    existing = _storage.notification_group_get(group_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")
    body = await req.json()
    group = {
        "id": group_id,
        "group_name": body.get("group_name", existing["group_name"]),
        "subreddits": body.get("subreddits", existing["subreddits"]),
        "email_dl": body.get("email_dl", existing["email_dl"]),
        "slack_channel": body.get("slack_channel", existing.get("slack_channel", "")),
        "enabled": body.get("enabled", existing["enabled"]),
        "priority_filter": body.get("priority_filter", existing["priority_filter"]),
    }
    _storage.notification_group_upsert(group)
    return {"ok": True, "group": _storage.notification_group_get(group_id)}


@app.delete("/api/notifications/groups/{group_id}")
async def delete_notification_group(group_id: str):
    deleted = _storage.notification_group_delete(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"ok": True}


@app.get("/api/notifications/log")
async def get_notification_log(limit: int = 50):
    """Recent notification history with sent status."""
    return {"log": _storage.notification_log_recent(limit)}


@app.post("/api/notifications/test/{group_id}")
async def test_notification_group(group_id: str, real: bool = Query(False, description="If true and Slack webhook is configured, actually POST to Slack instead of dry-run.")):
    """Send a test notification to verify group config.

    Default is dry-run (just logs). Pass `?real=true` to actually POST the
    message to Slack — requires SLACK_WEBHOOK_URL env var (or the
    `notifications.slack.webhook_url` config key) to be set.

    Email is always dry-run from this endpoint — SMTP config isn't
    per-group, so a real send requires the global email config to be filled
    in and cannot be safely tested from a per-group button.
    """
    g = _storage.notification_group_get(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    results = {}
    if g["email_dl"]:
        from src.notifications.email import send as send_email
        from src.utils.config import EmailChannelConfig
        cfg = EmailChannelConfig(
            enabled=True,
            dry_run=True,  # always dry-run for test (SMTP is global, not per-group)
            from_addr=NOTIFICATION_SENDER,
            recipients=g["email_dl"],
        )
        results["email"] = send_email(cfg, subject="[RSI Test] Notification group test", body=f"Test notification for group: {g['group_name']}")
    if g.get("slack_channel"):
        from src.notifications.slack import send as send_slack
        from src.utils.config import SlackChannelConfig
        # Only "real" send needs a webhook URL. Pull from env or global config.
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook_url and _config and getattr(_config, "notifications", None):
            webhook_url = getattr(_config.notifications.slack, "webhook_url", "") or ""
        cfg = SlackChannelConfig(
            enabled=True,
            dry_run=not real,
            webhook_url=webhook_url,
            channel=g["slack_channel"],
        )
        results["slack"] = send_slack(
            cfg,
            title="[RSI Test]",
            body=f"Test notification for group: {g['group_name']} — sent from the Notifications page.",
        )
    outcome = "sent" if (real and results.get("slack", {}).get("ok") and not results.get("slack", {}).get("dry_run")) else "dry_run"
    _storage.notification_log_insert(group_id, "test", "test", outcome)
    return {"ok": True, "real": real, "results": results}


@app.get("/api/notifications/subreddits")
async def get_available_subreddits():
    """Return list of tracked subreddits for group config UI."""
    import csv
    subs = []
    csv_path = Path("data/subreddits_clean.csv")
    if csv_path.exists():
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                subs.append({
                    "subreddit": row.get("subreddit", ""),
                    "group": row.get("group", ""),
                    "macro_group": row.get("macro_group", ""),
                })
    return {"subreddits": subs}


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def start_dashboard():
    """Start the dashboard server."""
    import uvicorn
    config = load_config()
    # `reload=True` deadlocks when a pipeline subprocess is running: uvicorn
    # waits for background tasks to finish before restarting, and pipeline
    # runs can take 20+ minutes. Gate it behind DASHBOARD_RELOAD=1 so devs
    # can opt in when they're not running long jobs.
    reload_enabled = os.environ.get("DASHBOARD_RELOAD") == "1"
    uvicorn.run(
        "src.dashboard.api:app",
        host=config.dashboard.host,
        port=config.dashboard.port,
        reload=reload_enabled,
    )


if __name__ == "__main__":
    start_dashboard()
