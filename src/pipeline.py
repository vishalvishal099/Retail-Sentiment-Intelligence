"""
Retail Sentiment Intelligence — Main Pipeline Orchestrator
Coordinates: Ingestion → Preprocess → Trust Filter → Analysis → Aggregation → Alert → Storage
"""

import csv
import time
from enum import Enum
from pathlib import Path

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
        log.info("cycle_start")
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
            for unit in scored:
                self.storage.upsert("raw_posts", unit)
            trusted = [u for u in scored if u.get("is_trusted")]
            flagged = [u for u in scored if not u.get("is_trusted")]
            total_trusted += len(trusted)
            total_flagged += len(flagged)

            # Vision enrichment: caption image-bearing posts so the
            # downstream sentiment + aspect models see image content too.
            self._enrich_with_vision(scored)

            # Analyse everything (trusted + flagged); flagged stays out of trend metrics via trust_score
            analyses = self.analyzer.analyze_batch(scored)
            if analyses:
                self.storage.upsert_batch("analyses", analyses)
            total_analyzed += len(analyses)
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

        all_units = []
        for subreddit in self._subreddits:
            try:
                last_utc = self.cursor.get_cursor(subreddit)
                if last_utc == 0.0:
                    last_utc = (datetime.now(timezone.utc) - timedelta(days=self.config.ingestion.backfill_days)).timestamp()
                    log.info("backfill_start", subreddit=subreddit, days=self.config.ingestion.backfill_days)

                posts = list(fetch_posts_arctic(subreddit, since_utc=last_utc))

                for post in posts:
                    comments = fetch_comments_arctic(
                        post["id"],
                        limit=self.config.ingestion.max_comments_per_post,
                        min_score=self.config.ingestion.comment_min_score,
                    )
                    all_units.extend(comments)

                all_units.extend(posts)

                if posts:
                    newest_utc = max(p.get("created_timestamp", 0) for p in posts)
                    self.cursor.update_cursor(subreddit, newest_utc, posts[0]["id"])

            except Exception as e:
                log.error("subreddit_ingest_failed", subreddit=subreddit, provider="arctic_shift", error=str(e))
                continue

        return all_units

    def _ingest_praw(self) -> list[dict]:
        """Fetch via PRAW (requires Reddit API credentials)."""
        from src.ingestion.fetcher import fetch_posts, get_backfill_timestamp
        from src.ingestion.comments import fetch_comments

        all_units = []
        for subreddit in self._subreddits:
            try:
                last_utc = self.cursor.get_cursor(subreddit)
                if last_utc == 0.0:
                    last_utc = get_backfill_timestamp(self.config.ingestion.backfill_days)
                    log.info("backfill_start", subreddit=subreddit, days=self.config.ingestion.backfill_days)

                posts = list(fetch_posts(self.reddit, subreddit, last_fetched_utc=last_utc))

                for post in posts:
                    comments = fetch_comments(self.reddit, post["id"], self.config.ingestion)
                    all_units.extend(comments)

                all_units.extend(posts)

                if posts:
                    newest_utc = max(p.get("created_timestamp", 0) for p in posts)
                    self.cursor.update_cursor(subreddit, newest_utc, posts[0]["id"])

            except Exception as e:
                log.error("subreddit_ingest_failed", subreddit=subreddit, provider="praw", error=str(e))
                continue

        return all_units

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
            cached = image_preprocess.fetch_and_normalize(post_id, url, vcfg)
            if not cached:
                continue
            caption = vision.caption(cached)
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
      --max-batches N      Cap how many batches --analyze-pending will process.
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

    if "--once" in sys.argv:
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
