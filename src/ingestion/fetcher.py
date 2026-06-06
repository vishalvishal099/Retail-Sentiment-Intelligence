"""
Retail Sentiment Intelligence — Post Fetcher
Fetches new posts from subreddits since last cursor.
Supports initial 90-day backfill and incremental hourly fetches.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Generator

from src.ingestion.reddit_client import RedditClient
from src.utils.config import IngestionConfig
from src.utils.privacy import hash_username
from src.utils.logger import get_logger

log = get_logger("fetcher")


def fetch_posts(
    client: RedditClient,
    subreddit_name: str,
    last_fetched_utc: float = 0.0,
    limit: int = 500,
) -> Generator[dict, None, None]:
    """
    Fetch posts from a subreddit newer than last_fetched_utc.
    Yields normalized post dicts.

    For initial backfill: last_fetched_utc = now - 90 days.
    For incremental: last_fetched_utc = timestamp of last successful fetch.
    """
    subreddit = client.get_subreddit(subreddit_name)

    try:
        for submission in subreddit.new(limit=limit):
            # Skip posts older than our cursor
            if submission.created_utc <= last_fetched_utc:
                break

            # Skip removed/deleted
            if submission.removed_by_category or submission.selftext == "[deleted]":
                continue

            yield _normalize_post(submission, subreddit_name)

    except Exception as e:
        log.error("fetch_failed", subreddit=subreddit_name, error=str(e))
        raise


def get_backfill_timestamp(days: int = 90) -> float:
    """Get the UTC timestamp for N days ago (used for initial backfill)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()


def _normalize_post(submission, subreddit_name: str) -> dict:
    """Convert PRAW submission to our normalized schema."""
    author_name = str(submission.author) if submission.author else "[deleted]"

    return {
        "id": f"reddit_{submission.id}",
        "source": "reddit",
        "subreddit": subreddit_name,
        "unit_type": "post",
        "parent_post_id": None,
        "author_hash": hash_username(author_name),
        "title": submission.title or "",
        "body": submission.selftext or "",
        "score": submission.score,
        "num_comments": submission.num_comments,
        "created_utc": datetime.fromtimestamp(submission.created_utc, tz=timezone.utc).isoformat(),
        "created_timestamp": submission.created_utc,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "url": f"https://reddit.com{submission.permalink}",
        "author_metadata": {
            "account_age_days": _account_age(submission.author),
            "total_karma": _author_karma(submission.author),
            "is_verified": False,
        },
        "processing_status": "pending",
        "trust_score": None,
        "model_used": None,
        "model_version": None,
    }


def _account_age(author) -> int:
    """Get account age in days. Returns 0 if unavailable."""
    if author is None:
        return 0
    try:
        created = author.created_utc
        return int((time.time() - created) / 86400)
    except Exception:
        return 0


def _author_karma(author) -> int:
    """Get total karma. Returns 0 if unavailable."""
    if author is None:
        return 0
    try:
        return author.link_karma + author.comment_karma
    except Exception:
        return 0
