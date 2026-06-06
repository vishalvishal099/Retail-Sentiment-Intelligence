"""
Retail Sentiment Intelligence — Scheduler Entry Point
Runs the pipeline on a configurable interval with APScheduler.
Also triggers hourly/daily aggregation at appropriate intervals.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.pipeline import RetailSentimentPipeline

log = get_logger("scheduler")


def run_scheduler():
    """Start the scheduled pipeline with APScheduler."""
    setup_logging()
    config = load_config()

    pipeline = RetailSentimentPipeline(config)
    pipeline.initialize()

    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler()

    # Pipeline cycle (default: every 30 minutes)
    scheduler.add_job(
        pipeline.run_cycle,
        "interval",
        minutes=config.ingestion.interval_minutes,
        id="pipeline_cycle",
        name="Main Pipeline Cycle",
    )

    # Hourly aggregation
    scheduler.add_job(
        lambda: pipeline.aggregator.aggregate_window("hourly"),
        "cron",
        minute=5,  # 5 minutes past each hour
        id="hourly_aggregate",
        name="Hourly Aggregation",
    )

    # Daily aggregation
    scheduler.add_job(
        lambda: pipeline.aggregator.aggregate_window("daily"),
        "cron",
        hour=0,
        minute=15,  # 00:15 daily
        id="daily_aggregate",
        name="Daily Aggregation",
    )

    # Weekly aggregation
    scheduler.add_job(
        lambda: pipeline.aggregator.aggregate_window("weekly"),
        "cron",
        day_of_week="mon",
        hour=0,
        minute=30,
        id="weekly_aggregate",
        name="Weekly Aggregation",
    )

    log.info("scheduler_started",
             pipeline_interval=config.ingestion.interval_minutes,
             jobs=len(scheduler.get_jobs()))

    # Run once immediately
    pipeline.run_cycle()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler_shutdown")
        scheduler.shutdown()


if __name__ == "__main__":
    run_scheduler()
