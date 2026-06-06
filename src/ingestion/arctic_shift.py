"""
Retail Sentiment Intelligence — Arctic Shift Fetcher
Fetches Reddit posts via the free Arctic Shift API (no credentials needed).
Drop-in replacement for PRAW-based fetcher when Reddit API access is unavailable.

Uses subprocess+curl as transport to bypass Python SSL issues on corporate networks.
API docs: https://arctic-shift.photon-reddit.com/
"""

import json
import subprocess
import time
from datetime import datetime, timezone, timedelta
from typing import Generator
from urllib.parse import urlencode

from src.ingestion.preprocess import preprocess_units
from src.utils.privacy import hash_username
from src.utils.logger import get_logger

log = get_logger("arctic_shift")

BASE_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
COMMENTS_URL = "https://arctic-shift.photon-reddit.com/api/comments/search"


def _curl_get(url: str, timeout: int = 30) -> dict | None:
    """Fetch JSON from a URL using curl (bypasses Python SSL issues). One retry on transient failures."""
    cmd = [
        "curl", "-sS", "--tls-max", "1.2", "--connect-timeout", "15",
        "--max-time", str(timeout), url,
    ]
    for attempt in (1, 2):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            log.error("curl_timeout", url=url, attempt=attempt)
            continue
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                log.error("curl_json_error", url=url, error=str(e))
                return None
        log.warning("curl_failed", url=url, rc=result.returncode,
                    stderr=result.stderr[:200], attempt=attempt)
        time.sleep(1.0)
    return None


def fetch_posts_arctic(
    subreddit: str,
    since_utc: float = 0.0,
    limit: int = 500,
    self_posts_only: bool = False,
) -> Generator[dict, None, None]:
    """
    Fetch posts from Arctic Shift API for a given subreddit.
    Yields normalized post dicts compatible with our pipeline schema.

    Args:
        subreddit: Subreddit name (without r/ prefix)
        since_utc: Only return posts created after this UTC timestamp
        limit: Max posts to fetch (API max per request is 100)
        self_posts_only: If True, only fetch text posts (better for sentiment)
    """
    fetched = 0
    before = None  # pagination: fetch posts created before this timestamp

    while fetched < limit:
        batch_size = min(100, limit - fetched)
        params = {
            "subreddit": subreddit,
            "limit": str(batch_size),
            "sort": "desc",
        }

        if since_utc > 0:
            params["after"] = str(int(since_utc))

        if before:
            params["before"] = str(int(before))

        if self_posts_only:
            params["is_self"] = "true"

        url = f"{BASE_URL}?{urlencode(params)}"
        data = _curl_get(url)
        if data is None:
            break

        posts = data.get("data", [])
        if not posts:
            break

        for post in posts:
            created_utc = post.get("created_utc", 0)

            # Skip if older than our cursor
            if since_utc > 0 and created_utc <= since_utc:
                continue

            # Skip removed/deleted
            selftext = post.get("selftext", "") or ""
            if selftext.lower() in ("[deleted]", "[removed]"):
                continue

            normalized = _normalize_post(post, subreddit)
            if normalized:
                yield normalized
                fetched += 1

        # Check if there's more data
        if len(posts) < batch_size:
            break

        # Use the last post's created_utc as cursor for next page
        last_created = posts[-1].get("created_utc", 0)
        if last_created > 0:
            before = last_created
        else:
            break

        # Rate limiting: be polite to the free API
        time.sleep(0.5)

    log.info("arctic_shift_fetch_complete", subreddit=subreddit, total_fetched=fetched)


def fetch_comments_arctic(
    post_id: str,
    limit: int = 10,
    min_score: int = 3,
) -> list[dict]:
    """
    Fetch comments for a specific post from Arctic Shift.

    Args:
        post_id: Reddit post ID (without reddit_ prefix)
        limit: Max comments to return
        min_score: Minimum comment score to include
    """
    raw_id = post_id.replace("reddit_", "")

    if limit <= 0:
        return []

    params = {
        "link_id": f"t3_{raw_id}",
        "limit": str(max(limit * 2, 1)),
        "sort": "desc",
    }
    url = f"{COMMENTS_URL}?{urlencode(params)}"
    data = _curl_get(url)
    if not data:
        return []

    comments = []
    for comment in (data.get("data") or []):
        if len(comments) >= limit:
            break

        score = comment.get("score", 0)
        if score < min_score:
            continue

        body = comment.get("body", "") or ""
        if body.lower() in ("[deleted]", "[removed]", ""):
            continue

        author_name = comment.get("author", "[deleted]")
        subreddit = comment.get("subreddit", "")
        comment_id = comment.get("id", "")
        created_utc = comment.get("created_utc", 0)

        comments.append({
            "id": f"reddit_c_{comment_id}",
            "source": "reddit",
            "subreddit": subreddit,
            "unit_type": "comment",
            "parent_post_id": post_id,
            "parent_comment_id": None,
            "author_hash": hash_username(author_name),
            "title": "",
            "body": body,
            "score": score,
            "num_comments": 0,
            "created_utc": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
            "created_timestamp": created_utc,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "url": f"https://www.reddit.com/r/{subreddit}/comments/{raw_id}/_/{comment_id}/",
            "author_metadata": {
                "account_age_days": 0,
                "total_karma": 0,
                "is_verified": False,
            },
            "processing_status": "pending",
            "trust_score": None,
            "model_used": None,
            "model_version": None,
        })

    log.info("arctic_shift_comments_fetched", post_id=post_id, count=len(comments))
    return comments


def backfill_subreddit(
    subreddit: str,
    days: int = 90,
    limit: int = 2000,
    self_posts_only: bool = False,
) -> list[dict]:
    """
    Backfill posts from a subreddit for the past N days.
    Returns a list of normalized, preprocessed post dicts.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    posts = list(fetch_posts_arctic(subreddit, since_utc=since, limit=limit, self_posts_only=self_posts_only))
    log.info("backfill_raw", subreddit=subreddit, days=days, raw_count=len(posts))

    # Run through preprocessor (dedup, language filter, cleaning)
    clean_posts = preprocess_units(posts)
    log.info("backfill_clean", subreddit=subreddit, clean_count=len(clean_posts))
    return clean_posts


def _normalize_post(post: dict, subreddit: str) -> dict | None:
    """Convert Arctic Shift post JSON to our normalized schema."""
    post_id = post.get("id", "")
    if not post_id:
        return None

    author_name = post.get("author", "[deleted]")
    created_utc = post.get("created_utc", 0)
    selftext = post.get("selftext", "") or ""
    title = post.get("title", "") or ""

    # Skip image-only posts with no text
    if not selftext and not title:
        return None

    permalink = post.get("permalink", f"/r/{subreddit}/comments/{post_id}/")

    return {
        "id": f"reddit_{post_id}",
        "source": "reddit",
        "subreddit": subreddit,
        "unit_type": "post",
        "parent_post_id": None,
        "author_hash": hash_username(author_name),
        "title": title,
        "body": selftext,
        "score": post.get("score", 0),
        "num_comments": post.get("num_comments", 0),
        "created_utc": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
        "created_timestamp": created_utc,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "url": f"https://www.reddit.com{permalink}",
        "author_metadata": {
            "account_age_days": 0,
            "total_karma": 0,
            "is_verified": False,
        },
        "processing_status": "pending",
        "trust_score": None,
        "model_used": None,
        "model_version": None,
    }
