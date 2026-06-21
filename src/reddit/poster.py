"""Reddit reply poster.

`post_reply(post_id, reply_text, token, cfg)` is the only public function.
- Validates inputs (non-empty reply, post_id with `reddit_` prefix or `t1_/t3_`).
- Enforces a process-wide rate limit (`cfg.rate_limit_seconds`).
- Honours `cfg.dry_run`: just logs the intent and returns a mock success.
- Otherwise hits Reddit's `/api/comment` endpoint with the user's bearer token.

Returns a dict with `{ok, posted_id, dry_run, error}`.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import requests

from src.utils.config import RedditOAuthConfig
from src.utils.logger import get_logger

log = get_logger("reddit_poster")

COMMENT_URL = "https://oauth.reddit.com/api/comment"

# Process-wide last-post timestamp keyed by username. Reddit's spam filter is
# per-account, so this lives in memory for the lifetime of the API process.
_LAST_POST_AT: dict[str, float] = {}
_LOCK = threading.Lock()


def _coerce_thing_id(post_id: str) -> str:
    """Map our internal id (`reddit_abc123`) to Reddit's thing-id format
    (`t3_abc123` for posts). If already prefixed (`t1_`/`t3_`), pass through.
    """
    if post_id.startswith(("t1_", "t3_")):
        return post_id
    if post_id.startswith("reddit_"):
        return f"t3_{post_id[len('reddit_'):]}"
    # Fallback: treat as raw post id.
    return f"t3_{post_id}"


def _rate_limit_ok(username: str, window_seconds: int) -> tuple[bool, float]:
    """Return (allowed, seconds_remaining). Updates last-post on success-side
    only; caller must call `mark_posted()` after a successful POST.
    """
    if window_seconds <= 0:
        return True, 0.0
    with _LOCK:
        last = _LAST_POST_AT.get(username, 0.0)
        elapsed = time.time() - last
        if elapsed >= window_seconds:
            return True, 0.0
        return False, window_seconds - elapsed


def mark_posted(username: str) -> None:
    with _LOCK:
        _LAST_POST_AT[username] = time.time()


def post_reply(
    post_id: str,
    reply_text: str,
    cfg: RedditOAuthConfig,
    access_token: Optional[str] = None,
    username: Optional[str] = None,
) -> dict:
    """Post `reply_text` as a top-level comment on `post_id`.

    When `cfg.dry_run` is True, no network call is made — the intent is logged
    and the function returns `{ok: True, dry_run: True, ...}`. This is the
    default-on safety so the integration can ship before live credentials are
    in place.
    """
    text = (reply_text or "").strip()
    if not text:
        return {"ok": False, "error": "empty_reply"}
    if len(text) > 10_000:
        return {"ok": False, "error": "reply_too_long"}
    thing_id = _coerce_thing_id(post_id)

    user_key = username or "anonymous"
    allowed, remaining = _rate_limit_ok(user_key, cfg.rate_limit_seconds)
    if not allowed:
        log.warning("reddit_post_rate_limited",
                    username=user_key, remaining_seconds=int(remaining))
        return {
            "ok": False,
            "error": "rate_limited",
            "retry_after_seconds": int(remaining),
        }

    if cfg.dry_run:
        log.info("reddit_post_dry_run",
                 thing_id=thing_id, length=len(text), username=user_key)
        mark_posted(user_key)
        return {
            "ok": True,
            "dry_run": True,
            "posted_id": None,
            "thing_id": thing_id,
            "length": len(text),
        }

    if not access_token:
        return {"ok": False, "error": "not_authenticated"}

    try:
        resp = requests.post(
            COMMENT_URL,
            data={"thing_id": thing_id, "text": text, "api_type": "json"},
            headers={
                "Authorization": f"bearer {access_token}",
                "User-Agent": cfg.user_agent,
            },
            timeout=20,
        )
    except requests.RequestException as e:
        log.error("reddit_post_network_error", error=str(e))
        return {"ok": False, "error": f"network: {e}"}

    if resp.status_code != 200:
        log.error("reddit_post_failed", status=resp.status_code, body=resp.text[:200])
        return {"ok": False, "error": f"status_{resp.status_code}"}

    payload = resp.json()
    things = (((payload.get("json") or {}).get("data") or {}).get("things")) or []
    posted_id = ""
    if things:
        posted_id = (things[0].get("data") or {}).get("name", "")
    errors = ((payload.get("json") or {}).get("errors") or [])
    if errors:
        log.error("reddit_post_api_errors", errors=errors)
        return {"ok": False, "error": "api_error", "details": errors}

    mark_posted(user_key)
    log.info("reddit_post_success", thing_id=thing_id, posted_id=posted_id, username=user_key)
    return {"ok": True, "dry_run": False, "posted_id": posted_id, "thing_id": thing_id}
