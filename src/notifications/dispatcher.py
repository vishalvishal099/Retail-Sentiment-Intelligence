"""Fan-out dispatcher — formats a lifecycle event and broadcasts to every
enabled channel. Returns per-channel results so callers can log them.
"""

from __future__ import annotations

from typing import Optional

from src.notifications import slack as slack_channel
from src.notifications import email as email_channel
from src.utils.config import NotificationsConfig
from src.utils.logger import get_logger

log = get_logger("notif_dispatch")


def dispatch_negative_post(
    cfg: NotificationsConfig,
    *,
    post_id: str,
    title: str,
    subreddit: str,
    sentiment_score: float,
    confidence: float,
    body_excerpt: str,
    reddit_url: Optional[str] = None,
) -> dict:
    """Notify analysts that a high-confidence negative post just landed.

    Skipped silently when both channels are disabled. With both dry-run, this
    is a logger-only path.
    """
    headline = f"Negative post in r/{subreddit}: {title[:120]}"
    body = (
        f"Sentiment score: {sentiment_score:+.2f} (confidence {confidence:.0%})\n"
        f"Post: {post_id}\n\n"
        f"{body_excerpt[:600]}"
    )
    subject = f"[RSI] r/{subreddit} negative — {title[:90]}"

    results: dict = {}
    if cfg.slack.enabled:
        results["slack"] = slack_channel.send(cfg.slack, title=headline, body=body, link=reddit_url)
    if cfg.email.enabled:
        results["email"] = email_channel.send(cfg.email, subject=subject, body=body, link=reddit_url)

    if not results:
        log.debug("notif_dispatch_no_channels", post_id=post_id)
    else:
        log.info("notif_dispatch_done", post_id=post_id, channels=list(results.keys()))

    return results
