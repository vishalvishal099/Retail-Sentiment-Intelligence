"""Phase 3 — Reddit OAuth + reply posting.

Two responsibilities:
- `oauth.py` runs the authorization-code flow (login → callback → token).
- `poster.py` posts replies via the `/api/comment` endpoint, with rate-limit
  and a `dry_run` mode that just logs the intent.
"""
