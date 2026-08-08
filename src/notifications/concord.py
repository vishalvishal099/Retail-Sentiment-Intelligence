"""Concord (postRichMessage) adapter — Walmart internal Slack delivery.

Uses the `magic-slack-notifications` Concord project to post a rich Slack
message with title / message / status / footer / fields. Token is read from
the env var `CONCORD_API_TOKEN` — never committed.

Mirrors this curl call:

    curl -X POST https://concord.prod.walmart.com/api/v1/process \\
      -H 'Authorization: <token>' \\
      -F org=GIF \\
      -F project=magic-slack-notifications \\
      -F repo=magic-slack-notifications \\
      -F entryPoint=postRichMessage \\
      -F activeProfiles=prod \\
      -F 'request={"arguments":{"title":"...","message":"...","status":"...",
                                "footer":"...","fields":[...]}};type=application/octet-stream'
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests
import urllib3

from src.utils.logger import get_logger

log = get_logger("notif_concord")

# Walmart internal endpoints use self-signed corporate root CA (Zscaler MITM).
# Same pattern as src/analysis/llm_client.py — silence the noise, then verify=False.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Statuses accepted by the postRichMessage entry point (from Walmart MAGIC docs).
VALID_STATUSES = {"info", "success", "warning", "error"}


def _normalize_channel(channel: Optional[str]) -> Optional[str]:
    if not channel:
        return None
    cleaned = channel.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:]
    cleaned = cleaned.strip()
    return cleaned or None


def send(
    *,
    url: str,
    org: str,
    project: str,
    repo: str,
    entry_point: str,
    active_profiles: str,
    title: str,
    message: str,
    status: str = "info",
    footer: Optional[str] = None,
    fields: Optional[list[dict[str, Any]]] = None,
    channel: Optional[str] = None,
    token: Optional[str] = None,
    timeout: int = 15,
) -> dict:
    """Post a rich Slack message via Concord. Returns {ok, dry_run, error, ...}.

    `token` defaults to $CONCORD_API_TOKEN. If missing, returns an ok=False
    result rather than raising. `channel` is passed through in the request
    arguments so per-group overrides work (e.g. #retail-alerts vs #ops).
    """
    if status not in VALID_STATUSES:
        return {"ok": False, "error": f"invalid_status_{status}"}

    tok = token or os.environ.get("CONCORD_API_TOKEN", "").strip()
    if not tok:
        return {"ok": False, "error": "concord_token_missing"}

    request_payload: dict[str, Any] = {
        "arguments": {
            "title": title,
            "message": message,
            "status": status,
        }
    }
    if footer:
        request_payload["arguments"]["footer"] = footer
    if fields:
        request_payload["arguments"]["fields"] = fields
    normalized_channel = _normalize_channel(channel)
    if normalized_channel:
        request_payload["arguments"]["channel"] = normalized_channel

    files = {
        "org": (None, org),
        "project": (None, project),
        "repo": (None, repo),
        "entryPoint": (None, entry_point),
        "activeProfiles": (None, active_profiles),
        "request": (None, json.dumps(request_payload), "application/octet-stream"),
    }

    headers = {"Authorization": tok}

    try:
        resp = requests.post(url, headers=headers, files=files, timeout=timeout, verify=False)
    except requests.RequestException as e:
        log.error("concord_send_failed_network", error=str(e))
        return {"ok": False, "error": f"network: {e}"}

    if resp.status_code >= 300:
        log.error("concord_send_failed", status=resp.status_code, body=resp.text[:400])
        return {"ok": False, "error": f"status_{resp.status_code}", "body": resp.text[:400]}

    body: Any = None
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:400]

    log.info("concord_send_ok", title=title, status=status)
    return {"ok": True, "dry_run": False, "response": body}
