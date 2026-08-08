"""Slack channel — routes through Concord (Walmart internal) when configured,
falls back to a plain webhook otherwise. Dry-run-aware."""

from __future__ import annotations

from typing import Optional

import requests

from src.notifications import concord as concord_channel
from src.utils.config import SlackChannelConfig
from src.utils.logger import get_logger

log = get_logger("notif_slack")


def _sentiment_to_status(sentiment_score: Optional[float]) -> str:
    """Map a signed sentiment score in [-1, +1] to a Concord status enum."""
    if sentiment_score is None:
        return "info"
    if sentiment_score <= -0.5:
        return "error"
    if sentiment_score <= -0.2:
        return "warning"
    if sentiment_score >= 0.2:
        return "success"
    return "info"


def send(
    cfg: SlackChannelConfig,
    *,
    title: str,
    body: str,
    link: Optional[str] = None,
    fields: Optional[list[dict]] = None,
    sentiment_score: Optional[float] = None,
) -> dict:
    if not cfg.enabled:
        return {"ok": False, "skipped": True, "reason": "slack_disabled"}

    if cfg.dry_run:
        log.info(
            "slack_dry_run",
            mode="concord" if cfg.concord_org else "webhook",
            title=title,
            channel=cfg.channel,
            body_len=len(body),
        )
        return {"ok": True, "dry_run": True}

    # Prefer Concord if configured
    if cfg.concord_org:
        return concord_channel.send(
            url=cfg.concord_url,
            org=cfg.concord_org,
            project=cfg.concord_project,
            repo=cfg.concord_repo,
            entry_point=cfg.concord_entry_point,
            active_profiles=cfg.concord_active_profiles,
            title=title,
            message=body if not link else f"{body}\n<{link}|Open post>",
            status=_sentiment_to_status(sentiment_score),
            footer=cfg.concord_footer or None,
            fields=fields,
            channel=cfg.channel or None,
        )

    # Fallback: legacy webhook path
    if not cfg.webhook_url:
        return {"ok": False, "error": "webhook_url_missing"}

    text_lines = [f"*{title}*", body]
    if link:
        text_lines.append(f"<{link}|Open post>")
    text = "\n".join(text_lines)
    payload = {"text": text, "channel": cfg.channel} if cfg.channel else {"text": text}

    try:
        resp = requests.post(cfg.webhook_url, json=payload, timeout=10)
    except requests.RequestException as e:
        log.error("slack_send_failed_network", error=str(e))
        return {"ok": False, "error": f"network: {e}"}

    if resp.status_code >= 300:
        log.error("slack_send_failed", status=resp.status_code, body=resp.text[:200])
        return {"ok": False, "error": f"status_{resp.status_code}"}

    log.info("slack_send_ok", title=title)
    return {"ok": True, "dry_run": False}
