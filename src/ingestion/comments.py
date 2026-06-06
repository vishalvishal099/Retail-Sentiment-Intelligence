"""
Retail Sentiment Intelligence — Comment Fetcher
Fetches top comments per post (depth ≤ 2, score ≥ 3, max 10 per post).
Each comment becomes a separate analysis unit.
"""

import time
from datetime import datetime, timezone

from src.ingestion.reddit_client import RedditClient
from src.utils.config import IngestionConfig
from src.utils.privacy import hash_username
from src.utils.logger import get_logger

log = get_logger("comments")


def fetch_comments(
    client: RedditClient,
    submission_id: str,
    config: IngestionConfig,
) -> list[dict]:
    """
    Fetch top comments for a Reddit post.
    Returns normalized comment dicts as separate analysis units.

    Constraints (from requirements):
    - depth ≤ config.comment_max_depth (default 2)
    - min score ≥ config.comment_min_score (default 3)
    - max config.max_comments_per_post (default 10)
    """
    # Strip 'reddit_' prefix if present
    raw_id = submission_id.replace("reddit_", "")

    try:
        submission = client.reddit.submission(id=raw_id)
        submission.comment_sort = "best"
        submission.comments.replace_more(limit=0)  # Don't expand "more comments"

        comments = []
        _collect_comments(
            comment_forest=submission.comments,
            post_id=submission_id,
            subreddit=str(submission.subreddit),
            depth=0,
            max_depth=config.comment_max_depth,
            min_score=config.comment_min_score,
            max_count=config.max_comments_per_post,
            results=comments,
        )

        log.info("comments_fetched", post_id=submission_id, count=len(comments))
        return comments

    except Exception as e:
        log.error("comment_fetch_failed", post_id=submission_id, error=str(e))
        return []


def _collect_comments(
    comment_forest,
    post_id: str,
    subreddit: str,
    depth: int,
    max_depth: int,
    min_score: int,
    max_count: int,
    results: list,
):
    """Recursively collect comments up to max_depth and max_count."""
    if depth > max_depth or len(results) >= max_count:
        return

    for comment in comment_forest:
        if len(results) >= max_count:
            break

        # Skip deleted or low-score comments
        if not hasattr(comment, "body") or comment.body in ("[deleted]", "[removed]"):
            continue
        if comment.score < min_score:
            continue

        author_name = str(comment.author) if comment.author else "[deleted]"

        results.append({
            "id": f"reddit_c_{comment.id}",
            "source": "reddit",
            "subreddit": subreddit,
            "unit_type": "comment",
            "parent_post_id": post_id,
            "parent_comment_id": f"reddit_c_{comment.parent_id.replace('t1_', '')}" if comment.parent_id.startswith("t1_") else None,
            "author_hash": hash_username(author_name),
            "title": "",
            "body": comment.body,
            "score": comment.score,
            "num_comments": 0,
            "created_utc": datetime.fromtimestamp(comment.created_utc, tz=timezone.utc).isoformat(),
            "created_timestamp": comment.created_utc,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "url": f"https://reddit.com{comment.permalink}",
            "author_metadata": {
                "account_age_days": _comment_author_age(comment.author),
                "total_karma": _comment_author_karma(comment.author),
                "is_verified": False,
            },
            "processing_status": "pending",
            "trust_score": None,
            "model_used": None,
            "model_version": None,
        })

        # Recurse into replies
        if hasattr(comment, "replies") and comment.replies:
            _collect_comments(
                comment_forest=comment.replies,
                post_id=post_id,
                subreddit=subreddit,
                depth=depth + 1,
                max_depth=max_depth,
                min_score=min_score,
                max_count=max_count,
                results=results,
            )


def _comment_author_age(author) -> int:
    if author is None:
        return 0
    try:
        return int((time.time() - author.created_utc) / 86400)
    except Exception:
        return 0


def _comment_author_karma(author) -> int:
    if author is None:
        return 0
    try:
        return author.link_karma + author.comment_karma
    except Exception:
        return 0
