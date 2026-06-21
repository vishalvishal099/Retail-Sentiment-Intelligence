"""Email channel — stdlib smtplib only, dry_run-aware. No new deps."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

from src.utils.config import EmailChannelConfig
from src.utils.logger import get_logger

log = get_logger("notif_email")


def send(cfg: EmailChannelConfig, *, subject: str, body: str, link: Optional[str] = None) -> dict:
    if not cfg.enabled:
        return {"ok": False, "skipped": True, "reason": "email_disabled"}

    if cfg.dry_run:
        log.info(
            "email_dry_run",
            subject=subject,
            recipients=cfg.recipients,
            from_addr=cfg.from_addr,
            body_len=len(body),
        )
        return {"ok": True, "dry_run": True}

    if not cfg.recipients:
        return {"ok": False, "error": "no_recipients"}
    if not cfg.smtp_host:
        return {"ok": False, "error": "smtp_host_missing"}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_addr or (cfg.smtp_user or "rsi-alerts@example.com")
    msg["To"] = ", ".join(cfg.recipients)
    full_body = body if not link else f"{body}\n\nLink: {link}\n"
    msg.set_content(full_body)

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
            if cfg.use_tls:
                server.starttls()
            if cfg.smtp_user and cfg.smtp_password:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        log.error("email_send_failed", error=str(e))
        return {"ok": False, "error": f"smtp: {e}"}

    log.info("email_send_ok", subject=subject, recipients=len(cfg.recipients))
    return {"ok": True, "dry_run": False}
