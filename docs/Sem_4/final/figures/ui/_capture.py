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
    # (route, screenshot name, needs_week_filter)
    # `needs_week_filter=True` selects the "Last 7 Days" range on the page's
    # date-range dropdown before capture — the default "Today" filter often
    # shows an empty state on a freshly-seeded dev DB.
    ("/",              "brand_health",         True),
    ("/pipeline",      "pipeline",             True),
    ("/alerts",        "alert_feed",           True),
    ("/posts",         "post_explorer",        False),   # explorer defaults to a wider window
    ("/review",        "review_validate",      True),
    ("/lifecycle",     "lifecycle_kanban",     False),   # kanban shows all open cards
    ("/insights",      "insights_competitor",  False),   # insights already uses a rolling window
    ("/notifications", "notifications",        False),
]


def _crop_to_max_aspect(path: Path) -> None:
    img = Image.open(path)
    w, h = img.size
    max_h = int(w * MAX_ASPECT_H_OVER_W)
    if h > max_h:
        img.crop((0, 0, w, max_h)).save(path, optimize=True)
        print(f"   cropped {h}px -> {max_h}px")


def _select_week_range(page) -> None:
    """Pick 'Last 7 Days' on the page's date-range dropdown, if one exists.

    RSI pages render a native <select> whose <option value="week"> is the
    7-day preset. We match on option value rather than label so the click
    works even if the visible text changes.
    """
    try:
        # Every RSI range picker uses value="week" for the 7-day preset.
        selects = page.locator("select").filter(has=page.locator('option[value="week"]'))
        if selects.count() > 0:
            selects.first.select_option("week")
            page.wait_for_timeout(1200)   # let the API re-fetch fire
            print("   selected 'Last 7 Days'")
    except Exception as exc:
        print(f"   (range select skipped: {exc})")


def main() -> None:
    with sync_playwright() as p:
        # Use system Google Chrome — bundled Playwright chromium is not
        # downloadable in this network-restricted environment.
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1.5)
        page = ctx.new_page()
        for path, name, needs_week in PAGES:
            url = f"{BASE}{path}"
            print(f"→ {name}  ({url})")
            page.goto(url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1200)
            if needs_week:
                _select_week_range(page)
            # Give charts a moment to finish animating.
            page.wait_for_timeout(1500)
            out = OUT / f"{name}.png"
            page.screenshot(path=str(out), full_page=True)
            _crop_to_max_aspect(out)
            print(f"   wrote {out}  ({out.stat().st_size // 1024} KB)")

        _capture_smart_reply(page)
        browser.close()


def _capture_smart_reply(page) -> None:
    """Capture the Smart Reply Composer on a negative-sentiment review card.

    Workflow the analyst actually performs:
      1. Open /review?sentiment=negative so 'Generate Drafts' is allowed
         (the backend rejects non-negative posts).
      2. On the first eligible card, expand the 'Advanced' section so the
         aspect + trust-override controls are visible.
      3. Click 'Generate Drafts' and wait for GPT-4o + Mistral + Smart
         Composer drafts to render.
      4. Screenshot just that card so the composer fills the frame.
    """
    name = "smart_reply_composer"
    url = f"{BASE}/review?sentiment=negative"
    print(f"→ {name}  ({url})")
    page.goto(url, wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(1500)

    # Pin the first eligible card as an ELEMENT HANDLE so the reference stays
    # stable after React re-renders. A live locator would re-evaluate and
    # match the *next* card once ours flips out of the 'Generate Drafts' state.
    card_locator = page.locator(".rounded-2xl.shadow-card").filter(
        has=page.locator("button", has_text="Generate Drafts")
    )
    if card_locator.count() == 0:
        print("   (no eligible card found — skipped)")
        return
    card = card_locator.first.element_handle()
    if card is None:
        print("   (could not resolve card handle — skipped)")
        return
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(400)

    # Expand 'Advanced' inside THIS card.
    advanced = card.query_selector('button:has-text("Advanced")')
    if advanced:
        try:
            advanced.click()
            page.wait_for_timeout(400)
            print("   opened Advanced panel")
        except Exception as exc:
            print(f"   (Advanced toggle skipped: {exc})")

    # Trigger draft generation from THIS card.
    gen_btn = card.query_selector('button:has-text("Generate Drafts")')
    if gen_btn is None:
        print("   (Generate Drafts button vanished — skipped)")
        return
    print("   clicking 'Generate Drafts' (Ollama + gateway may take ~10-20 s)...")
    gen_btn.click()

    # Poll THIS card's button text until it flips to 'Regenerate Both'.
    for _ in range(60):
        page.wait_for_timeout(1000)
        regen = card.query_selector('button:has-text("Regenerate Both")')
        if regen is not None:
            print("   all three drafts rendered")
            break
    else:
        print("   (timed out waiting for drafts — capturing anyway)")
    page.wait_for_timeout(1200)   # let the drafts settle into their boxes

    card.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    out = OUT / f"{name}.png"
    try:
        card.screenshot(path=str(out))
    except Exception:
        page.screenshot(path=str(out), full_page=True)
        _crop_to_max_aspect(out)
    print(f"   wrote {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
