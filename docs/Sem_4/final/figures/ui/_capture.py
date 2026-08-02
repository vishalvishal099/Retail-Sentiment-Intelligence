#!/usr/bin/env python3
"""Full-page dashboard screenshots via Playwright.

Replaces the old headless-Chrome `_capture.sh` which was limited to the
1440×900 viewport and truncated any page longer than the fold (e.g. the
Insights & Competitor page had its aspect radar + recommendations cut off).

Usage:  BASE=http://localhost:3001 python _capture.py
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://localhost:3001")
OUT = Path(__file__).resolve().parent

# Cap tall screenshots so LaTeX \includegraphics[width=\linewidth] doesn't
# balloon the image to several pages tall. 2.0 keeps ~1.5 folds of scrolled
# content visible while still fitting comfortably on a single report page.
MAX_ASPECT_H_OVER_W = 2.0

PAGES = [
    ("/",              "brand_health"),
    ("/alerts",        "alert_feed"),
    ("/posts",         "post_explorer"),
    ("/review",        "review_validate"),
    ("/lifecycle",     "lifecycle_kanban"),
    ("/insights",      "insights_competitor"),
    ("/notifications", "notifications"),
]


def _crop_to_max_aspect(path: Path) -> None:
    img = Image.open(path)
    w, h = img.size
    max_h = int(w * MAX_ASPECT_H_OVER_W)
    if h > max_h:
        img.crop((0, 0, w, max_h)).save(path, optimize=True)
        print(f"   cropped {h}px -> {max_h}px")


def main() -> None:
    with sync_playwright() as p:
        # Use system Google Chrome — bundled Playwright chromium is not
        # downloadable in this network-restricted environment.
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1.5)
        page = ctx.new_page()
        for path, name in PAGES:
            url = f"{BASE}{path}"
            print(f"→ {name}  ({url})")
            page.goto(url, wait_until="networkidle", timeout=30_000)
            # Give charts a moment to finish animating.
            page.wait_for_timeout(1500)
            out = OUT / f"{name}.png"
            page.screenshot(path=str(out), full_page=True)
            _crop_to_max_aspect(out)
            print(f"   wrote {out}  ({out.stat().st_size // 1024} KB)")
        browser.close()


if __name__ == "__main__":
    main()
