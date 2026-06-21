"""Slack channel — single webhook POST, dry_run-aware."""

from __future__ import annotations

from typing import Optional

import requests

from src.utils.config import SlackChannelConfig
from src.utils.logger import get_logger

log = get_logger("notif_slack")


def send(cfg: SlackChannelConfig, *, title: str, body: str, link: Optional[str] = None) -> dict:
    if not cfg.enabled:
        return {"ok": False, "skipped": True, "reason": "slack_disabled"}

    text_lines = [f"*{title}*", body]
    if link:
        text_lines.append(f"<{link}|Open post>")
    text = "\n".join(text_lines)

    payload = {"text": text, "channel": cfg.channel} if cfg.channel else {"text": text}

    if cfg.dry_run:
        log.info("slack_dry_run", title=title, channel=cfg.channel, body_len=len(body))
        return {"ok": True, "dry_run": True}

    if not cfg.webhook_url:
        return {"ok": False, "error": "webhook_url_missing"}

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
