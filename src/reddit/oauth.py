"""Reddit OAuth2 — authorization_code flow.

Stateless helper functions used by the dashboard endpoints. No global state:
the FastAPI session middleware owns the {access_token, refresh_token, username}
triple, and these helpers just talk to Reddit's `/api/v1/authorize` and
`/api/v1/access_token` endpoints.

Spec: https://github.com/reddit-archive/reddit/wiki/oauth2

Notes:
- Uses HTTP Basic auth (client_id : client_secret) for the token exchange.
- `state` parameter is a CSRF token; we generate one per login and verify in
  the callback.
"""

from __future__ import annotations

import secrets
import time
import urllib.parse
from dataclasses import dataclass

import requests

from src.utils.config import RedditOAuthConfig
from src.utils.logger import get_logger

log = get_logger("reddit_oauth")

AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
ME_URL = "https://oauth.reddit.com/api/v1/me"


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: float  # unix ts
    scope: str
    username: str = ""

    def is_expired(self, leeway: int = 60) -> bool:
        return time.time() >= (self.expires_at - leeway)

    def to_session(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "username": self.username,
        }

    @classmethod
    def from_session(cls, data: dict) -> "TokenBundle | None":
        if not data or not data.get("access_token"):
            return None
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=float(data.get("expires_at", 0)),
            scope=data.get("scope", ""),
            username=data.get("username", ""),
        )


def build_authorize_url(cfg: RedditOAuthConfig, state: str) -> str:
    """Return the URL the browser should be redirected to for consent."""
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": cfg.redirect_uri,
        "duration": "permanent",
        "scope": cfg.scope,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def new_state_token() -> str:
    """CSRF state token for the OAuth round-trip."""
    return secrets.token_urlsafe(24)


def exchange_code_for_token(cfg: RedditOAuthConfig, code: str) -> TokenBundle:
    """Trade the `code` from the callback for an access + refresh token."""
    if not cfg.client_id or not cfg.client_secret:
        raise RuntimeError("reddit_oauth.client_id/client_secret not configured")

    resp = requests.post(
        TOKEN_URL,
        auth=(cfg.client_id, cfg.client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
        },
        headers={"User-Agent": cfg.user_agent},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("reddit_token_exchange_failed", status=resp.status_code, body=resp.text[:200])
        raise RuntimeError(f"token exchange failed: {resp.status_code}")
    payload = resp.json()
    bundle = TokenBundle(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", ""),
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
        scope=payload.get("scope", cfg.scope),
    )
    bundle.username = fetch_me(cfg, bundle.access_token)
    log.info("reddit_token_obtained", username=bundle.username, scope=bundle.scope)
    return bundle


def refresh_token(cfg: RedditOAuthConfig, refresh: str) -> TokenBundle:
    """Use the refresh token to get a new access token. Reddit refresh tokens
    do not rotate, so we keep the same `refresh_token` value."""
    resp = requests.post(
        TOKEN_URL,
        auth=(cfg.client_id, cfg.client_secret),
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        headers={"User-Agent": cfg.user_agent},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("reddit_token_refresh_failed", status=resp.status_code, body=resp.text[:200])
        raise RuntimeError(f"token refresh failed: {resp.status_code}")
    payload = resp.json()
    bundle = TokenBundle(
        access_token=payload["access_token"],
        refresh_token=refresh,
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
        scope=payload.get("scope", cfg.scope),
    )
    bundle.username = fetch_me(cfg, bundle.access_token)
    log.info("reddit_token_refreshed", username=bundle.username)
    return bundle


def fetch_me(cfg: RedditOAuthConfig, access_token: str) -> str:
    """Return the authenticated user's name. Empty string on failure."""
    try:
        resp = requests.get(
            ME_URL,
            headers={
                "Authorization": f"bearer {access_token}",
                "User-Agent": cfg.user_agent,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("name", "")
        log.warning("reddit_me_failed", status=resp.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("reddit_me_error", error=str(e))
    return ""
