"""Fan-out dispatcher — formats a lifecycle event and broadcasts to every
enabled channel. Returns per-channel results so callers can log them.

Group-based routing: notifications only fire when a post's subreddit belongs
to a configured notification group AND the post meets P1/P2 priority criteria.
"""

from __future__ import annotations

from typing import Optional

from src.notifications import slack as slack_channel
from src.notifications import email as email_channel
from src.utils.config import NotificationsConfig, EmailChannelConfig, SlackChannelConfig
from src.utils.logger import get_logger

log = get_logger("notif_dispatch")

# Default sender — matches config on the Notifications page
SENDER_EMAIL = "vishal.singh1@walmart.com"

# Priority thresholds
P1_TRUST = 0.70
P1_CONF = 0.80
P2_TRUST = 0.50
P2_CONF = 0.60


def classify_priority(trust_score: float, confidence: float) -> Optional[str]:
    """Return 'P1', 'P2', or None based on trust × confidence thresholds."""
    if trust_score >= P1_TRUST and confidence >= P1_CONF:
        return "P1"
    if trust_score >= P2_TRUST and confidence >= P2_CONF:
        return "P2"
    return None


def dispatch_for_groups(
    storage,
    *,
    post_id: str,
    title: str,
    subreddit: str,
    sentiment_score: float,
    confidence: float,
    trust_score: float,
    body_excerpt: str,
    reddit_url: Optional[str] = None,
) -> dict:
    """Route notifications through configured groups. Only fires for P1/P2."""
    tier = classify_priority(trust_score, confidence)
    if tier is None:
        log.debug("notif_skip_not_priority", post_id=post_id, trust=trust_score, conf=confidence)
        return {"skipped": True, "reason": "not_p1_p2"}

    # Find groups that include this subreddit
    groups = storage.notification_groups_for_subreddit(subreddit)
    if not groups:
        log.debug("notif_skip_no_group", post_id=post_id, subreddit=subreddit)
        return {"skipped": True, "reason": "no_matching_group"}

    results = {}
    for g in groups:
        # Check if group's priority filter includes this tier
        if tier not in g.get("priority_filter", ["P1", "P2"]):
            continue

        group_id = g["id"]
        headline = f"[{tier}] Negative post in r/{subreddit}: {title[:120]}"
        body = (
            f"Priority: {tier}\n"
            f"Sentiment score: {sentiment_score:+.2f} (confidence {confidence:.0%})\n"
            f"Trust score: {trust_score:.2f}\n"
            f"Group: {g['group_name']}\n"
            f"Post: {post_id}\n\n"
            f"{body_excerpt[:600]}"
        )
        subject = f"[RSI {tier}] r/{subreddit} — {title[:90]}"

        group_results = {}

        # Email
        if g.get("email_dl"):
            email_cfg = EmailChannelConfig(
                enabled=True,
                dry_run=False,
                from_addr=SENDER_EMAIL,
                recipients=g["email_dl"],
            )
            email_res = email_channel.send(email_cfg, subject=subject, body=body, link=reddit_url)
            group_results["email"] = email_res
            storage.notification_log_insert(
                group_id, post_id, "email",
                "sent" if email_res.get("ok") and not email_res.get("dry_run") else
                "dry_run" if email_res.get("dry_run") else "failed",
                email_res.get("error"),
            )

        # Slack
        if g.get("slack_channel"):
            slack_cfg = SlackChannelConfig(
                enabled=True,
                dry_run=False,
                channel=g["slack_channel"],
            )
            slack_res = slack_channel.send(slack_cfg, title=headline, body=body, link=reddit_url)
            group_results["slack"] = slack_res
            storage.notification_log_insert(
                group_id, post_id, "slack",
                "sent" if slack_res.get("ok") and not slack_res.get("dry_run") else
                "dry_run" if slack_res.get("dry_run") else "failed",
                slack_res.get("error"),
            )

        results[group_id] = group_results
        log.info("notif_group_dispatched", group=g["group_name"], tier=tier, post_id=post_id)

    return {"tier": tier, "groups_notified": len(results), "results": results}


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
    """Legacy dispatcher — notify analysts that a high-confidence negative post just landed.

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
