#!/usr/bin/env bash
# Headless-Chrome screenshot capture for RSI dashboard pages.
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE="${BASE:-http://localhost:3003}"
OUT="$(cd "$(dirname "$0")" && pwd)"
SIZE="1440,900"

shoot () {
  local path="$1" name="$2"
  echo "→ $name  ($BASE$path)"
  "$CHROME" \
    --headless=new --disable-gpu --hide-scrollbars \
    --window-size=$SIZE \
    --virtual-time-budget=6000 \
    --screenshot="$OUT/$name.png" \
    "$BASE$path" >/dev/null 2>&1 || true
}

shoot "/"              brand_health
shoot "/alerts"        alert_feed
shoot "/posts"         post_explorer
shoot "/review"        review_validate
shoot "/lifecycle"     lifecycle_kanban
shoot "/insights"      insights_competitor
shoot "/notifications" notifications

ls -la "$OUT"/*.png
