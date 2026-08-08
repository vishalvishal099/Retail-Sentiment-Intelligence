#!/usr/bin/env python3
"""Standalone verify script for the Concord Slack adapter.

Usage:
    python scripts/test_concord_slack.py              # dry-run (safe)
    python scripts/test_concord_slack.py --live       # actually post to Slack

CONCORD_API_TOKEN and CONCORD_ORG are read from .env (loaded by
src/utils/config.py). No hard-coded credentials in this script.
"""

from __future__ import annotations

import argparse
import os
import sys
from pprint import pprint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before importing the notification modules so os.environ is populated
from src.utils.config import load_dotenv  # noqa: F401 -- side-effect import

from src.notifications import slack as slack_channel
from src.utils.config import SlackChannelConfig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Actually POST to Concord (dry_run off)")
    ap.add_argument(
        "--channel",
        default="",
        help="Override Slack channel (defaults to notification-group config or SlackChannelConfig default)",
    )
    args = ap.parse_args()

    # Defaults (concord_org, project, etc.) auto-populate from .env
    cfg = SlackChannelConfig(enabled=True, dry_run=not args.live)
    if args.channel:
        cfg.channel = args.channel

    if args.live and not os.environ.get("CONCORD_API_TOKEN"):
        print("ERROR: CONCORD_API_TOKEN not set in .env. Aborting live send.", file=sys.stderr)
        return 2
    if args.live and not cfg.concord_org:
        print("ERROR: CONCORD_ORG not set in .env. Aborting live send.", file=sys.stderr)
        return 2

    print(f"--- config ---")
    print(f"  dry_run           = {cfg.dry_run}")
    print(f"  channel           = {cfg.channel}")
    print(f"  concord_org       = {cfg.concord_org}")
    print(f"  concord_project   = {cfg.concord_project}")
    print(f"  concord_url       = {cfg.concord_url}")
    print(f"  token in env      = {'yes' if os.environ.get('CONCORD_API_TOKEN') else 'no'}")
    print()

    result = slack_channel.send(
        cfg,
        title="Alert: P1 negative post on r/walmart",
        body="Sentiment score dropped to -0.87 with trust 0.82 · confidence 0.91",
        link="http://localhost:3001/posts?sentiment=negative&range=today",
        sentiment_score=-0.87,
        fields=[
            {"title": "Subreddit",  "value": "r/walmart", "short": True},
            {"title": "Priority",   "value": "P1",        "short": True},
            {"title": "Trust",      "value": "0.82",      "short": True},
            {"title": "Confidence", "value": "0.91",      "short": True},
        ],
    )
    print("--- send result ---")
    pprint(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
