"""
Retail Sentiment Intelligence — Main Pipeline Orchestrator
Coordinates: Ingestion → Preprocess → Trust Filter → Analysis → Aggregation → Alert → Storage
"""

import csv
import os
import time
import uuid
from enum import Enum
from pathlib import Path

# ─── transformers 4.57.3 offline-mode workaround ─────────────────────────────
# PreTrainedTokenizerBase._patch_mistral_regex (added in 4.55+) unconditionally
# calls huggingface_hub.model_info() to check "is this a mistral tokenizer?".
# With HF_HUB_OFFLINE=1 that raises OfflineModeIsEnabled and crashes tokenizer
# loading. None of our models are Mistral variants (ModernBERT, DeBERTa, BART,
# RoBERTa, FLAN-T5, MiniLM), so replacing this classmethod with an identity
# passthrough is always the correct answer for this project. Must run before
# ANY code path that loads a tokenizer.
try:
    from transformers.tokenization_utils_base import PreTrainedTokenizerBase as _PTTB
    _PTTB._patch_mistral_regex = classmethod(lambda cls, tokenizer, *a, **k: tokenizer)
except Exception:
    pass

from src.utils.config import load_config, AppConfig
from src.utils.logger import setup_logging, get_logger
from src.utils.cost_tracker import CostTracker
from src.ingestion.preprocess import preprocess_units, reset_dedup_cache
from src.ingestion import image_preprocess
from src.storage.store import create_storage, StorageBackend
from src.storage.cursor import CursorTracker
from src.trust.scorer import TrustScorer
from src.analysis.llm_client import create_llm_client
from src.analysis.analyzer import SentimentAnalyzer
from src.analysis.vision import get_vision_client
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine

log = get_logger("pipeline")

# Overlap buffer (seconds) applied when computing the `since` boundary for the
# fetcher. Prevents posts at the cursor boundary (or indexed late by Arctic
# Shift) from being skipped between runs. Storage layer uses INSERT OR REPLACE
# on `id`, so re-fetched posts are deduplicated for free.
INGEST_OVERLAP_SECONDS = int(os.environ.get("INGEST_OVERLAP_SECONDS", "300"))


class PipelineStage(Enum):
    INGEST = "ingest"
    PREPROCESS = "preprocess"
    TRUST_FILTER = "trust_filter"
    ANALYZE = "analyze"
    AGGREGATE = "aggregate"
    ALERT = "alert"


class RetailSentimentPipeline:
    """
    Main orchestrator for the Retail Sentiment Intelligence pipeline.

    Pipeline Flow:
    1. INGEST:     Fetch new posts + comments from Reddit (PRAW)
    2. PREPROCESS: Clean, deduplicate, English filter
    3. TRUST:      Score credibility (metadata + dedup + LLM)
    4. ANALYZE:    Sentiment + Aspect classification (model-agnostic)
    5. AGGREGATE:  Time-window summaries and trend computation
    6. ALERT:      Detect anomalies and trigger notifications
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.storage: StorageBackend = None
        self.cursor: CursorTracker = None
        self.reddit = None  # Only set when fetcher_provider == "praw"
        self.trust_scorer: TrustScorer = None
        self.analyzer: SentimentAnalyzer = None
        self.aggregator: Aggregator = None
        self.alert_engine: AlertEngine = None
        self.cost_tracker: CostTracker = None
        self._subreddits: list[str] = []
        # Per-cycle staging: cursor advances are computed during _ingest but
        # only persisted after storage.upsert_batch(raw_posts) succeeds, so a
        # killed/crashed run never leaves a high-water-mark with no data.
        self._pending_cursor_advances: dict[str, tuple[float, str]] = {}
        # Per-cycle audit trail: one row per (run, subreddit) recording the
        # fetch window we actually asked for. Written via cursor history.
        self._run_id: str = uuid.uuid4().hex[:12]
        self._cursor_history: list[dict] = []

    def initialize(self):
        """Initialize all components."""
        setup_logging()

        # Storage
        self.storage = create_storage(self.config.storage)
        self.cursor = CursorTracker(self.config.storage.sqlite_path)

        # Reddit client only needed for PRAW provider
        if self.config.ingestion.fetcher_provider == "praw":
            from src.ingestion.reddit_client import RedditClient
            self.reddit = RedditClient(self.config.ingestion)

        # Cost tracking (required per R3.3)
        self.cost_tracker = CostTracker(
            log_file=self.config.llm.cost_log_file,
            daily_limit_usd=self.config.llm.daily_limit_usd,
        )

        # LLM client (model-agnostic, swappable via config)
        llm_client = create_llm_client(self.config.llm, self.cost_tracker)

        # Trust scorer
        self.trust_scorer = TrustScorer(self.config.trust, llm_client)

        # Analyzer
        self.analyzer = SentimentAnalyzer(llm_client, self.config.analysis)

        # Aggregator + Alert Engine
        self.aggregator = Aggregator(self.storage)
        self.alert_engine = AlertEngine(self.storage)

        # Load subreddits
        self._subreddits = self._load_subreddits()

        log.info("pipeline_initialized",
                 subreddits=len(self._subreddits),
                 fetcher_provider=self.config.ingestion.fetcher_provider,
                 llm_provider=self.config.llm.provider,
                 llm_model=self.config.llm.model,
                 storage=self.config.storage.provider)

    def run_cycle(self) -> dict:
        """Execute one full pipeline cycle."""
        # Fresh per-cycle audit state.
        self._run_id = uuid.uuid4().hex[:12]
        self._pending_cursor_advances = {}
        self._cursor_history = []
        log.info("cycle_start", run_id=self._run_id, overlap_seconds=INGEST_OVERLAP_SECONDS)
        reset_dedup_cache()

        # Stage 1: Ingest
        raw_units = self._ingest()
        log.info("stage_complete", stage="ingest", count=len(raw_units))

        if not raw_units:
            log.info("cycle_complete", result="no_new_data")
            return {"ingested": 0, "processed": 0, "trusted": 0, "flagged": 0, "analyzed": 0}

        # Stage 2: Preprocess
        clean_units = preprocess_units(raw_units, english_only=self.config.ingestion.english_only)
        log.info("stage_complete", stage="preprocess", count=len(clean_units))

        # Stage 2b: Vision enrichment (image-bearing posts get a caption).
        # Pure plumbing on the pipeline side; the model call lives in
        # src/analysis/vision.py. Failure is non-fatal — posts without
        # captions just fall through to text-only analysis.
        self._enrich_with_vision(clean_units)

        # Stage 3: Store raw (before trust/analysis so we don't lose data on crash)
        self.storage.upsert_batch("raw_posts", clean_units)

        # Stage 3b: Commit cursor advances NOW that raw_posts is persisted.
        # If the run dies after this point, the analyzer will pick up the
        # un-analyzed raw rows next cycle (analyze_pending_*) but the
        # ingest watermarks are safely advanced and won't refetch.
        self._commit_cursors()

        # Stage 4: Trust Filter
        scored_units = self.trust_scorer.score_batch(clean_units)
        trusted = [u for u in scored_units if u.get("is_trusted")]
        flagged = [u for u in scored_units if not u.get("is_trusted")]
        log.info("stage_complete", stage="trust", trusted=len(trusted), flagged=len(flagged))

        # Update storage with trust scores
        for unit in scored_units:
            self.storage.upsert("raw_posts", unit)

        # Stage 5: Analyze (all units — trusted get full analysis, flagged still get basic)
        analyses = self._analyze(scored_units)
        log.info("stage_complete", stage="analyze", count=len(analyses))

        # Store analyses
        self.storage.upsert_batch("analyses", analyses)

        # Auto-create lifecycle entries for high-confidence negatives
        self._maybe_create_lifecycle(analyses, scored_units)

        # Stage 6: Aggregate
        aggregate = self.aggregator.aggregate_window("daily")
        log.info("stage_complete", stage="aggregate", window=aggregate.get("time_window", "none"))

        # Stage 7: Alert Detection
        alerts = self.alert_engine.detect_all()
        if alerts:
            log.info("stage_complete", stage="alerts", count=len(alerts))
        for alert in alerts:
            self.storage.upsert("alerts", alert)

        result = {
            "ingested": len(raw_units),
            "processed": len(clean_units),
            "trusted": len(trusted),
            "flagged": len(flagged),
            "analyzed": len(analyses),
        }
        log.info("cycle_complete", **result)
        return result

    def analyze_pending(self, max_batches: int | None = None, batch_size: int | None = None) -> dict:
        """Process posts already in storage that are still pending analysis.

        No network calls. Useful for backfilling analysis when ingestion ran
        ahead of the analyzer (e.g. after a cursor reset that pulled 90 days of
        raw posts but only analyzed the latest cycle).
        """
        size = batch_size or self.config.llm.batch_size
        total_analyzed = 0
        total_trusted = 0
        total_flagged = 0
        batches = 0
        log.info("analyze_pending_start", batch_size=size)

        # Pre-flight: bulk-mark posts that already have an analyses row as
        # 'analyzed'. Without this, get_pending_posts (ORDER BY oldest first)
        # would iterate through every already-analyzed post and INSERT OR
        # REPLACE the same analysis row for hours before reaching truly
        # un-analyzed posts. This scans once and skips them all.
        try:
            skipped = self.storage._conn.execute(
                "UPDATE raw_posts SET processing_status = 'analyzed' "
                "WHERE processing_status = 'pending' "
                "  AND id IN (SELECT post_id FROM analyses)"
            ).rowcount
            self.storage._conn.commit()
            if skipped:
                log.info("analyze_pending_preflight", already_analyzed=skipped)
        except Exception as e:  # noqa: BLE001
            log.warning("analyze_pending_preflight_failed", error=str(e))

        while True:
            if max_batches is not None and batches >= max_batches:
                break
            if not self.cost_tracker.check_budget():
                log.warning("budget_exceeded", daily_spend=self.cost_tracker.get_daily_spend())
                break
            pending = self.storage.get_pending_posts(limit=size)
            if not pending:
                break

            # Trust scoring (may flip status to flagged_low_trust)
            scored = self.trust_scorer.score_batch(pending)
            trusted = [u for u in scored if u.get("is_trusted")]
            flagged = [u for u in scored if not u.get("is_trusted")]
            total_trusted += len(trusted)
            total_flagged += len(flagged)

            # Vision enrichment: caption image-bearing posts so the
            # downstream sentiment + aspect models see image content too.
            # Mutates `scored` with image_fetch metadata + image_caption.
            self._enrich_with_vision(scored)

            # Persist raw_posts now — after both trust AND vision have mutated
            # the unit — so the DB carries trust_score, is_trusted, and the
            # image_fetch outcome (status/http_code/checked_at) needed by
            # /api/ingestion/image-failures. Previous ordering upserted before
            # vision and dropped the image metadata.
            for unit in scored:
                self.storage.upsert("raw_posts", unit)

            # Analyse everything (trusted + flagged); flagged stays out of trend metrics via trust_score
            analyses = self.analyzer.analyze_batch(scored)
            if analyses:
                self.storage.upsert_batch("analyses", analyses)
                self._maybe_create_lifecycle(analyses, scored)
            total_analyzed += len(analyses)
            # Mark every post in this batch as analyzed so the next iteration
            # of get_pending_posts moves forward. Without this the loop would
            # re-process the oldest 200 pending rows forever (they'd all be
            # INSERT-OR-REPLACE no-ops in analyses, so total_analyzed grows
            # but the DB doesn't change and newer posts never get reached).
            for unit in scored:
                uid = unit.get("id")
                if uid:
                    new_status = "flagged_low_trust" if not unit.get("is_trusted") else "analyzed"
                    self.storage.update_status(uid, new_status)
            batches += 1
            log.info(
                "analyze_pending_batch",
                batch=batches,
                size=len(pending),
                analyzed=len(analyses),
                trusted=len(trusted),
                flagged=len(flagged),
                total_analyzed=total_analyzed,
            )

        # Refresh aggregates once at the end
        try:
            self.aggregator.aggregate_window("daily")
        except Exception as e:  # noqa: BLE001
            log.warning("aggregate_after_backfill_failed", error=str(e))

        result = {
            "batches": batches,
            "analyzed": total_analyzed,
            "trusted": total_trusted,
            "flagged": total_flagged,
        }
        log.info("analyze_pending_complete", **result)
        return result

    # ─── Gap Analysis + Surgical Backfill ─────────────────────────────────

    def compute_gaps(self, gap_threshold_hours: float = 1.0) -> dict:
        """Report per-subreddit freshness.

        For every configured subreddit, returns the newest raw_post timestamp,
        the current cursor, the gap vs now, and whether the cursor drifted
        behind the data (which happens after a lookback-hours rewind that
        the upstream API subsequently returned zero results for).

        Pure read: does not modify cursors.
        """
        import sqlite3
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc).timestamp()
        db_path = self.config.storage.sqlite_path
        conn = sqlite3.connect(db_path)
        try:
            subs = []
            for sub in self._subreddits:
                row = conn.execute(
                    "SELECT MAX(created_timestamp), COUNT(*) FROM raw_posts "
                    "WHERE lower(subreddit) = lower(?)",
                    (sub,),
                ).fetchone()
                newest_post = row[0] or 0.0
                post_count = row[1] or 0
                cursor_utc = self.cursor.get_cursor(sub)
                # "true resume point" = furthest-ahead timestamp we can be
                # confident about, minus overlap. If we've never fetched or
                # both are 0, treat as needing full backfill.
                resume_ref = max(newest_post, cursor_utc)
                if resume_ref > 0:
                    resume_from = max(0.0, resume_ref - INGEST_OVERLAP_SECONDS)
                    gap_hours = (now_utc - resume_ref) / 3600.0
                else:
                    resume_from = 0.0
                    gap_hours = float("inf")
                cursor_drift_hours = (cursor_utc - newest_post) / 3600.0 if newest_post else 0.0
                needs_fetch = gap_hours > gap_threshold_hours
                subs.append({
                    "subreddit": sub,
                    "post_count": post_count,
                    "newest_post_utc": newest_post or None,
                    "cursor_utc": cursor_utc or None,
                    "gap_hours": None if gap_hours == float("inf") else round(gap_hours, 2),
                    "cursor_drift_hours": round(cursor_drift_hours, 2),
                    "resume_from_utc": resume_from,
                    "needs_fetch": needs_fetch,
                    "reason": (
                        "never_fetched" if resume_ref == 0
                        else "cursor_ahead_of_data" if cursor_drift_hours > 1
                        else "stale" if needs_fetch
                        else "fresh"
                    ),
                })
        finally:
            conn.close()

        stale = [s for s in subs if s["needs_fetch"]]
        drifted = [s for s in subs if s["cursor_drift_hours"] > 1]

        # Last successful ingest run — an ingest that actually pulled posts.
        # Excludes analyze-pending / retry-vision runs (they don't move
        # cursors) and stopped/failed runs. Populates the primary "Catch up
        # since…" button on the Data Health panel.
        last_run: dict | None = None
        try:
            import json as _json
            import sqlite3 as _sqlite3
            conn2 = _sqlite3.connect(db_path)
            row = conn2.execute(
                "SELECT id, started_at, finished_at, trigger, counters_json "
                "FROM pipeline_runs "
                "WHERE status = 'success' AND counters_json IS NOT NULL AND counters_json != '{}' "
                "  AND trigger IN ('scheduled', 'manual', 'backfill', 'fill-gaps') "
                "ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
            conn2.close()
            if row:
                counters = {}
                try:
                    counters = _json.loads(row[4] or "{}")
                except Exception:  # noqa: BLE001
                    pass
                ingested = int(counters.get("ingested", 0) or 0)
                # Skip "ingested=0" runs — they weren't real successful ingests
                # for the "catch up from" semantic.
                if ingested > 0:
                    finished_iso = row[2]
                    try:
                        finished_dt = datetime.fromisoformat(finished_iso.replace("Z", "+00:00"))
                        hours_ago = (now_utc - finished_dt.timestamp()) / 3600.0
                    except Exception:  # noqa: BLE001
                        hours_ago = None
                    last_run = {
                        "id": row[0],
                        "started_at": row[1],
                        "finished_at": finished_iso,
                        "trigger": row[3],
                        "ingested": ingested,
                        "analyzed": int(counters.get("analyzed", 0) or 0),
                        "hours_ago": round(hours_ago, 1) if hours_ago is not None else None,
                    }
        except Exception as e:  # noqa: BLE001
            log.warning("gaps_last_run_lookup_failed", error=str(e))

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gap_threshold_hours": gap_threshold_hours,
            "totals": {
                "subreddits": len(subs),
                "stale": len(stale),
                "drifted": len(drifted),
                "fresh": len(subs) - len(stale),
            },
            "last_successful_ingest": last_run,
            "subreddits": subs,
        }

    def fill_gaps(
        self,
        since_utc: float | None = None,
        gap_threshold_hours: float = 1.0,
        dry_run: bool = False,
    ) -> dict:
        """Surgically rewind cursors for subs with a data gap, then optionally
        run one full cycle.

        Two modes:
          - `since_utc` given → rewind every sub whose cursor is more recent
            than `since_utc` back to `since_utc`. Matches the "since last
            successful run" mental model.
          - `since_utc` None  → per-sub: rewind to `max(newest_raw_post, cursor)
            - overlap_seconds`, but only if `gap_hours > gap_threshold_hours`.

        Never rewinds fresh subs (avoids wasted refetch). Always leaves cursor
        no earlier than what the data already shows.

        Returns the plan (what would be rewound); actual writes only happen
        when `dry_run` is False.
        """
        report = self.compute_gaps(gap_threshold_hours=gap_threshold_hours)
        plan = []
        for entry in report["subreddits"]:
            sub = entry["subreddit"]
            cursor = entry["cursor_utc"] or 0.0

            if since_utc is not None:
                # Anchor mode: rewind subs that are ahead of `since_utc`.
                # Never move cursor forward here.
                if cursor > since_utc:
                    new_cursor = since_utc
                else:
                    continue
            else:
                # Auto mode: only touch subs flagged as stale.
                if not entry["needs_fetch"]:
                    continue
                new_cursor = entry["resume_from_utc"]

            plan.append({
                "subreddit": sub,
                "old_cursor_utc": cursor,
                "new_cursor_utc": new_cursor,
                "rewind_hours": round((cursor - new_cursor) / 3600.0, 2) if cursor else None,
                "reason": entry["reason"],
            })
            if not dry_run:
                self.cursor.update_cursor(sub, new_cursor, "")

        log.info(
            "fill_gaps_plan",
            since_utc=since_utc,
            gap_threshold_hours=gap_threshold_hours,
            dry_run=dry_run,
            rewound=len(plan),
        )
        return {
            "dry_run": dry_run,
            "since_utc": since_utc,
            "gap_threshold_hours": gap_threshold_hours,
            "rewound_subreddits": len(plan),
            "plan": plan,
            "gap_report": report,
        }

    # ─── Stage Implementations ────────────────────────────────────────────

    def _ingest(self) -> list[dict]:
        """Fetch new posts + comments from all configured subreddits."""
        provider = self.config.ingestion.fetcher_provider
        if provider == "arctic_shift":
            return self._ingest_arctic_shift()
        if provider == "praw":
            return self._ingest_praw()
        raise ValueError(f"Unknown fetcher_provider: {provider!r} (expected 'arctic_shift' or 'praw')")

    def _ingest_arctic_shift(self) -> list[dict]:
        """Fetch via the free Arctic Shift API (no Reddit credentials needed)."""
        from src.ingestion.arctic_shift import fetch_posts_arctic, fetch_comments_arctic
        from datetime import datetime, timezone, timedelta

        now_utc = datetime.now(timezone.utc).timestamp()
        all_units = []
        total_subs = len(self._subreddits)
        for idx, subreddit in enumerate(self._subreddits, 1):
            cursor_utc = self.cursor.get_cursor(subreddit)
            if cursor_utc == 0.0:
                since_utc = (datetime.now(timezone.utc) - timedelta(days=self.config.ingestion.backfill_days)).timestamp()
                log.info("backfill_start", subreddit=subreddit, days=self.config.ingestion.backfill_days)
            else:
                # Apply overlap buffer so posts right at the boundary (or
                # indexed late by Arctic Shift) are not skipped. Dedup at the
                # storage layer handles any duplicates.
                since_utc = max(0.0, cursor_utc - INGEST_OVERLAP_SECONDS)
            until_utc = now_utc
            # Scale post limit with the window size so long backfills aren't
            # capped at the per-call default of 500. ~100 posts/day upper
            # bound covers even busy subs (r/walmart peaks ~70/day).
            window_days = max(1.0, (until_utc - since_utc) / 86400.0)
            fetch_limit = max(500, min(int(window_days * 120), 20000))
            fetched = 0
            status = "ok"
            error_msg = None
            # Per-sub progress event so the dashboard can show a live
            # "X of N subreddits, Y% covered" panel during long backfills.
            log.info(
                "subreddit_fetch_start",
                subreddit=subreddit, position=idx, total_subs=total_subs,
                since_utc=since_utc, until_utc=until_utc,
                window_days=round(window_days, 2), fetch_limit=fetch_limit,
            )
            def _on_page(info, _sub=subreddit, _since=since_utc, _until=until_utc):
                # Walk backward in time; oldest_utc shrinks toward since_utc.
                covered = max(0.0, _until - info["oldest_utc"])
                total = max(1.0, _until - _since)
                pct = min(100.0, round(100.0 * covered / total, 1))
                log.info(
                    "subreddit_fetch_progress",
                    subreddit=_sub, oldest_utc=info["oldest_utc"],
                    newest_utc=info["newest_utc"], page_size=info["page_size"],
                    total_fetched=info["total_fetched"], coverage_pct=pct,
                )
            try:
                posts = list(fetch_posts_arctic(
                    subreddit, since_utc=since_utc, limit=fetch_limit, on_page=_on_page,
                ))

                for post in posts:
                    comments = fetch_comments_arctic(
                        post["id"],
                        limit=self.config.ingestion.max_comments_per_post,
                        min_score=self.config.ingestion.comment_min_score,
                    )
                    all_units.extend(comments)

                all_units.extend(posts)
                fetched = len(posts)

                if posts:
                    newest_utc = max(p.get("created_timestamp", 0) for p in posts)
                    # Stage the advance; commit only after storage write.
                    self._pending_cursor_advances[subreddit] = (newest_utc, posts[0]["id"])

            except Exception as e:
                status = "failed"
                error_msg = str(e)
                log.error("subreddit_ingest_failed", subreddit=subreddit, provider="arctic_shift", error=error_msg)
            finally:
                self._cursor_history.append({
                    "run_id": self._run_id,
                    "subreddit": subreddit,
                    "provider": "arctic_shift",
                    "cursor_before": cursor_utc,
                    "since_utc": since_utc,
                    "until_utc": until_utc,
                    "overlap_seconds": INGEST_OVERLAP_SECONDS if cursor_utc > 0 else 0,
                    "fetched": fetched,
                    "status": status,
                    "error": error_msg,
                })
                log.info(
                    "subreddit_fetch_complete",
                    subreddit=subreddit, position=idx, total_subs=total_subs,
                    fetched=fetched, status=status,
                )

        return all_units

    def _ingest_praw(self) -> list[dict]:
        """Fetch via PRAW (requires Reddit API credentials)."""
        from src.ingestion.fetcher import fetch_posts, get_backfill_timestamp
        from src.ingestion.comments import fetch_comments
        from datetime import datetime, timezone

        all_units = []
        for subreddit in self._subreddits:
            cursor_utc = self.cursor.get_cursor(subreddit)
            if cursor_utc == 0.0:
                since_utc = get_backfill_timestamp(self.config.ingestion.backfill_days)
                log.info("backfill_start", subreddit=subreddit, days=self.config.ingestion.backfill_days)
            else:
                since_utc = max(0.0, cursor_utc - INGEST_OVERLAP_SECONDS)
            until_utc = datetime.now(timezone.utc).timestamp()
            fetched = 0
            status = "ok"
            error_msg = None
            try:
                posts = list(fetch_posts(self.reddit, subreddit, last_fetched_utc=since_utc))

                for post in posts:
                    comments = fetch_comments(self.reddit, post["id"], self.config.ingestion)
                    all_units.extend(comments)

                all_units.extend(posts)
                fetched = len(posts)

                if posts:
                    newest_utc = max(p.get("created_timestamp", 0) for p in posts)
                    self._pending_cursor_advances[subreddit] = (newest_utc, posts[0]["id"])

            except Exception as e:
                status = "failed"
                error_msg = str(e)
                log.error("subreddit_ingest_failed", subreddit=subreddit, provider="praw", error=error_msg)
            finally:
                self._cursor_history.append({
                    "run_id": self._run_id,
                    "subreddit": subreddit,
                    "provider": "praw",
                    "cursor_before": cursor_utc,
                    "since_utc": since_utc,
                    "until_utc": until_utc,
                    "overlap_seconds": INGEST_OVERLAP_SECONDS if cursor_utc > 0 else 0,
                    "fetched": fetched,
                    "status": status,
                    "error": error_msg,
                })

        return all_units

    def _commit_cursors(self) -> None:
        """Advance per-subreddit cursors after a successful storage write.

        Called by `run_cycle` only after `storage.upsert_batch('raw_posts', …)`
        succeeds. Also flushes the per-subreddit fetch-window audit rows.
        Both operations are idempotent / fail-soft.
        """
        for subreddit, (newest_utc, newest_id) in self._pending_cursor_advances.items():
            try:
                self.cursor.update_cursor(subreddit, newest_utc, newest_id)
            except Exception as e:  # noqa: BLE001
                log.error("cursor_commit_failed", subreddit=subreddit, error=str(e))
        # Flush history rows whether or not posts were fetched, so analysts
        # can see the empty windows too.
        for row in self._cursor_history:
            try:
                self.cursor.record_history(**row)
            except Exception as e:  # noqa: BLE001
                log.warning("cursor_history_write_failed", subreddit=row.get("subreddit"), error=str(e))
        log.info(
            "cursors_committed",
            run_id=self._run_id,
            advanced=len(self._pending_cursor_advances),
            history_rows=len(self._cursor_history),
        )
        self._pending_cursor_advances = {}
        self._cursor_history = []

    def _analyze(self, units: list[dict]) -> list[dict]:
        """Run sentiment + aspect analysis on units in batches."""
        if not self.cost_tracker.check_budget():
            log.warning("budget_exceeded", daily_spend=self.cost_tracker.get_daily_spend())
            return []

        analyses = []
        batch_size = self.config.llm.batch_size

        for i in range(0, len(units), batch_size):
            batch = units[i:i + batch_size]
            batch_results = self.analyzer.analyze_batch(batch)
            analyses.extend(batch_results)

            # Check budget after each batch
            if not self.cost_tracker.check_budget():
                log.warning("budget_hit_mid_batch", analyzed_so_far=len(analyses))
                break

        return analyses

    def _maybe_create_lifecycle(self, analyses: list[dict], scored_units: list[dict]) -> None:
        """Insert a `post_lifecycle` row + dispatch notifications for any
        post that just came back as confidently negative.

        Idempotent: skips posts that already have a lifecycle entry.
        Honours the `notifications.auto_lifecycle` flag.
        """
        notif_cfg = getattr(self.config, "notifications", None)
        if notif_cfg is None or not notif_cfg.auto_lifecycle:
            return

        threshold = float(notif_cfg.confidence_threshold or 0.7)
        unit_by_id = {u.get("id"): u for u in scored_units}

        from datetime import datetime, timezone
        from src.notifications.dispatcher import dispatch_negative_post, dispatch_for_groups

        created = 0
        for a in analyses:
            if a.get("sentiment") != "negative":
                continue
            conf = float(a.get("sentiment_confidence") or 0.0)
            if conf < threshold:
                continue
            post_id = a.get("post_id") or a.get("id")
            if not post_id:
                continue

            unit = unit_by_id.get(post_id) or {}
            now = datetime.now(timezone.utc).isoformat()
            title = unit.get("title") or unit.get("text", "")[:200]
            sub = a.get("subreddit") or unit.get("subreddit", "")
            score = float(a.get("sentiment_score") or 0.0)
            trust = float(unit.get("trust_score") or a.get("trust_score") or 0.0)

            try:
                # Group-based dispatch (P1/P2 only, per configured groups)
                dispatch_for_groups(
                    self.storage,
                    post_id=post_id,
                    title=title,
                    subreddit=sub,
                    sentiment_score=score,
                    confidence=conf,
                    trust_score=trust,
                    body_excerpt=(unit.get("text") or "")[:600],
                    reddit_url=unit.get("url") or unit.get("permalink", ""),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("notif_group_dispatch_error", post_id=post_id, error=str(e))

            try:
                # Legacy channel dispatch (if configured in YAML)
                dispatch_negative_post(
                    notif_cfg,
                    post_id=post_id,
                    title=title,
                    subreddit=sub,
                    sentiment_score=score,
                    confidence=conf,
                    body_excerpt=(unit.get("text") or "")[:600],
                    reddit_url=unit.get("url") or unit.get("permalink", ""),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("notif_dispatch_error", post_id=post_id, error=str(e))

    def _enrich_with_vision(self, units: list[dict]) -> None:
        """Caption image-bearing posts in place via the vision model.

        Mutates units: adds `image_caption` and `image_cached_path` when
        successful. Skipped entirely if vision is disabled in the model
        registry (config/models.yaml `models.vision.enabled: false`).
        """
        vcfg = self.config.models.vision
        if not vcfg.enabled:
            return
        targets = [u for u in units if image_preprocess.has_image(u) and not u.get("image_caption")]
        if not targets:
            return

        vision = get_vision_client(vcfg, ollama_url=self.config.llm.ollama_url)
        captioned = 0
        for unit in targets:
            url = image_preprocess.pick_image_url(unit)
            if not url:
                continue
            post_id = unit.get("id", "").replace("reddit_", "")
            cached, meta = image_preprocess.fetch_with_status(post_id, url, vcfg)
            # Persist the fetch outcome on the unit so the Pipeline UI can
            # surface which posts had their images deleted / throttled /
            # taken down. Kept as a compact dict — {status, http_code, error,
            # checked_at, cached?}.
            unit["image_fetch"] = {**meta, "url": url}
            if not cached:
                continue
            # Choose caption strategy based on config toggle. The multi-pass
            # enhanced() call is 4-8x slower, so keep it opt-in.
            caption = (
                vision.caption_enhanced(cached)
                if getattr(vcfg, "enhanced_captioning", False)
                else vision.caption(cached)
            )
            if caption:
                unit["image_caption"] = caption
                unit["image_cached_path"] = str(cached)
                captioned += 1
        log.info(
            "stage_complete",
            stage="vision",
            candidates=len(targets),
            captioned=captioned,
            model=vision.model_name,
        )

    def retry_vision(self, batch_size: int = 200) -> dict:
        """Re-caption image-bearing raw_posts that have no `image_caption`.

        Useful after Ollama was down during an ingest: pulls every raw post
        that has an image URL but no caption, runs vision on it, and
        upserts the post back. Idempotent and safe to re-run; posts that
        already have a caption are skipped.
        """
        from src.ingestion import image_preprocess
        from src.analysis.vision import get_vision_client

        vcfg = self.config.models.vision
        if not vcfg.enabled:
            log.info("retry_vision_disabled")
            return {"checked": 0, "captioned": 0, "skipped": 0, "failed": 0}

        # Read all candidates via raw SQL (much faster than full iteration).
        rows = self.storage._conn.execute(
            "SELECT id, data FROM raw_posts"
        ).fetchall()
        import json as _json
        units: list[dict] = []
        for r in rows:
            try:
                u = _json.loads(r["data"])
            except Exception:
                continue
            if image_preprocess.has_image(u) and not u.get("image_caption"):
                units.append(u)

        log.info("retry_vision_start", candidates=len(units))
        if not units:
            return {"checked": 0, "captioned": 0, "skipped": 0, "failed": 0}

        vision = get_vision_client(vcfg, ollama_url=self.config.llm.ollama_url)
        captioned = 0
        failed = 0
        for i, unit in enumerate(units):
            url = image_preprocess.pick_image_url(unit)
            if not url:
                failed += 1
                continue
            post_id = unit.get("id", "").replace("reddit_", "")
            cached = image_preprocess.fetch_and_normalize(post_id, url, vcfg)
            if not cached:
                failed += 1
                continue
            # Retry runs are off the hot path, so honour the enhanced flag here too.
            caption = (
                vision.caption_enhanced(cached)
                if getattr(vcfg, "enhanced_captioning", False)
                else vision.caption(cached)
            )
            if not caption:
                failed += 1
                continue
            unit["image_caption"] = caption
            unit["image_cached_path"] = str(cached)
            self.storage.upsert("raw_posts", unit)
            captioned += 1
            if (i + 1) % batch_size == 0:
                log.info("retry_vision_progress", done=i + 1, total=len(units), captioned=captioned, failed=failed)
        result = {
            "checked": len(units),
            "captioned": captioned,
            "failed": failed,
            "skipped": 0,
        }
        log.info("retry_vision_complete", **result)
        return result

    def _load_subreddits(self) -> list[str]:
        """Load the *enabled* subreddit list from the registry CSV.

        Honors the `enabled` flag managed by the dashboard's Pipeline page
        (see src/ingestion/subreddit_registry.py). Rows without that column
        are treated as enabled for backward compatibility.
        """
        from src.ingestion.subreddit_registry import load_all
        csv_path = Path(self.config.ingestion.subreddits_file)
        if not csv_path.exists():
            csv_path = Path(__file__).parent.parent / self.config.ingestion.subreddits_file
        if not csv_path.exists():
            log.warning("subreddits_file_not_found", path=str(csv_path))
            return ["walmart", "samsclub", "Sparkdriver", "OGPBackroom", "WalmartEmployees"]
        enabled = [e.subreddit for e in load_all(csv_path) if e.enabled]
        log.info("subreddits_loaded", total=len(enabled), source=str(csv_path))
        return enabled


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    """Run a single pipeline cycle (use with --once) or scheduled.

    Flags:
      --once               Run one full ingest+analyze+aggregate cycle and exit.
      --analyze-pending    Process posts already in storage with status 'pending'
                           through trust + analyzer. No network calls. Useful for
                           backfilling analysis after a large ingest.
      --retry-vision       Re-caption image-bearing raw_posts that have no caption
                           (e.g. when Ollama was down during ingest).
      --max-batches N      Cap how many batches --analyze-pending will process.
      --lookback-hours N   Override the default lookback window (hours).
      --fill-gaps          Surgical backfill: for every sub with a data gap,
                           rewind cursor to just after the newest raw_post it
                           already has, then run one cycle. Fresh subs are left
                           alone. Combine with --since to anchor at a specific
                           timestamp (e.g. the last successful run).
      --since ISO8601      Anchor timestamp for --fill-gaps (ISO 8601 UTC).
                           Any sub whose cursor is more recent than this gets
                           rewound to this timestamp.
      --gap-hours N        With --fill-gaps: only touch subs whose gap is
                           larger than N hours (default 1.0).
      --dry-run            With --fill-gaps: print the plan and exit without
                           modifying cursors or running the pipeline.
    """
    import sys

    config = load_config()
    pipeline = RetailSentimentPipeline(config)
    pipeline.initialize()

    if "--analyze-pending" in sys.argv:
        max_batches = None
        if "--max-batches" in sys.argv:
            idx = sys.argv.index("--max-batches")
            if idx + 1 < len(sys.argv):
                try:
                    max_batches = int(sys.argv[idx + 1])
                except ValueError:
                    pass
        result = pipeline.analyze_pending(max_batches=max_batches)
        print(f"Analyze-pending result: {result}")
        return

    if "--retry-vision" in sys.argv:
        result = pipeline.retry_vision()
        print(f"Retry-vision result: {result}")
        return

    if "--fill-gaps" in sys.argv:
        # Parse optional --since (ISO 8601 UTC) and --gap-hours
        from datetime import datetime, timezone
        since_utc: float | None = None
        gap_hours = 1.0
        dry_run = "--dry-run" in sys.argv
        if "--since" in sys.argv:
            idx = sys.argv.index("--since")
            if idx + 1 < len(sys.argv):
                raw = sys.argv[idx + 1]
                try:
                    # Accept both "2026-06-29" and full ISO. Default UTC.
                    dtv = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if dtv.tzinfo is None:
                        dtv = dtv.replace(tzinfo=timezone.utc)
                    since_utc = dtv.timestamp()
                except ValueError:
                    log.error("fill_gaps_bad_since", raw=raw)
                    print(f"ERROR: --since must be ISO 8601 UTC (got: {raw!r})")
                    sys.exit(2)
        if "--gap-hours" in sys.argv:
            idx = sys.argv.index("--gap-hours")
            if idx + 1 < len(sys.argv):
                try:
                    gap_hours = float(sys.argv[idx + 1])
                except ValueError:
                    pass

        plan = pipeline.fill_gaps(
            since_utc=since_utc,
            gap_threshold_hours=gap_hours,
            dry_run=dry_run,
        )

        # Human-readable summary for the CLI.
        print(f"\nFill-gaps plan ({'DRY RUN' if dry_run else 'APPLIED'})")
        print(f"  since_utc = {since_utc} ({datetime.fromtimestamp(since_utc, tz=timezone.utc).isoformat() if since_utc else 'auto'})")
        print(f"  gap_threshold_hours = {gap_hours}")
        print(f"  rewound {plan['rewound_subreddits']} subreddits:")
        for entry in plan["plan"]:
            new_iso = datetime.fromtimestamp(entry["new_cursor_utc"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if entry["new_cursor_utc"] else "—"
            print(f"    - {entry['subreddit']:22s} rewind {entry['rewind_hours']}h  → {new_iso}  ({entry['reason']})")
        print(f"  fresh (skipped): {plan['gap_report']['totals']['fresh']}")

        if dry_run:
            print("\nDry-run: no cursors modified, no cycle run. Re-run without --dry-run to apply.")
            return

        # After rewinding, run one normal cycle so the gap actually gets filled.
        result = pipeline.run_cycle()
        print(f"\nFill-gaps cycle result: {result}")
        return

    if "--once" in sys.argv:
        # Optional one-shot lookback override: walk every cursor back to
        # `now - lookback_hours` so this single cycle pulls a wider window.
        # Cursors then advance normally to the new high-water mark, so the
        # NEXT scheduled run resumes incremental ingestion without gaps.
        if "--lookback-hours" in sys.argv:
            idx = sys.argv.index("--lookback-hours")
            if idx + 1 < len(sys.argv):
                try:
                    hours = int(sys.argv[idx + 1])
                except ValueError:
                    hours = 0
                if hours > 0:
                    from datetime import datetime, timezone, timedelta
                    target = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
                    rewound = 0
                    for sub in pipeline._subreddits:
                        cur = pipeline.cursor.get_cursor(sub)
                        if cur == 0.0 or cur > target:
                            pipeline.cursor.update_cursor(sub, target, "")
                            rewound += 1
                    log.info("lookback_applied", hours=hours, subreddits_rewound=rewound)
        result = pipeline.run_cycle()
        print(f"Pipeline cycle result: {result}")
    else:
        # Scheduled mode
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()
        scheduler.add_job(
            pipeline.run_cycle,
            "interval",
            minutes=config.ingestion.interval_minutes,
        )
        log.info("scheduler_start", interval_minutes=config.ingestion.interval_minutes)
        # Run once immediately, then on schedule
        pipeline.run_cycle()
        scheduler.start()


if __name__ == "__main__":
    main()
