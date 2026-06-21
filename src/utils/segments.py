"""
Subreddit → segment mapping.

Loads `data/subreddits_clean.csv` once per process and exposes a small lookup
helper so ingestion can stamp `segment` on every post and the dashboard can
group/filter by it.

The CSV `group` column already encodes the segment (e.g. "Walmart core",
"Spark / last-mile"). We normalize that to a stable slug used everywhere.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger("segments")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "subreddits_clean.csv"

UNKNOWN_SEGMENT = "unknown"

# Macro grouping: every subreddit is either a Walmart-owned/Walmart-employee
# community ("walmart") or a competitor / general retail community
# ("competitor"). Loaded from the `macro_group` column of subreddits_clean.csv;
# unknown sources default to "competitor" so dashboards never silently drop them.
MACRO_WALMART = "walmart"
MACRO_COMPETITOR = "competitor"
MACRO_GROUPS = (MACRO_WALMART, MACRO_COMPETITOR)
DEFAULT_MACRO = MACRO_COMPETITOR


def _slugify(group: str) -> str:
    """Normalize CSV `group` text to a stable slug used by API + UI."""
    if not group:
        return UNKNOWN_SEGMENT
    s = group.strip().lower()
    s = s.replace("&", "and").replace("/", "_").replace("-", "_")
    out_chars = []
    prev_underscore = False
    for ch in s:
        if ch.isalnum():
            out_chars.append(ch)
            prev_underscore = False
        elif ch.isspace() or ch == "_":
            if not prev_underscore:
                out_chars.append("_")
                prev_underscore = True
    slug = "".join(out_chars).strip("_")
    return slug or UNKNOWN_SEGMENT


@lru_cache(maxsize=1)
def _load_map(csv_path: str = str(DEFAULT_CSV)) -> dict[str, str]:
    """Return {subreddit_lower: segment_slug}."""
    p = Path(csv_path)
    if not p.exists():
        log.warning("subreddit_segments_csv_missing", path=str(p))
        return {}
    mapping: dict[str, str] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sub = (row.get("subreddit") or "").strip()
            grp = (row.get("group") or "").strip()
            if not sub:
                continue
            mapping[sub.lower()] = _slugify(grp)
    log.info("subreddit_segments_loaded", count=len(mapping))
    return mapping


@lru_cache(maxsize=1)
def _load_macro_map(csv_path: str = str(DEFAULT_CSV)) -> dict[str, str]:
    """Return {subreddit_lower: macro_group} where macro_group ∈ {walmart, competitor}."""
    p = Path(csv_path)
    if not p.exists():
        return {}
    mapping: dict[str, str] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sub = (row.get("subreddit") or "").strip()
            macro = (row.get("macro_group") or "").strip().lower()
            if not sub:
                continue
            if macro not in MACRO_GROUPS:
                macro = DEFAULT_MACRO
            mapping[sub.lower()] = macro
    log.info("subreddit_macro_groups_loaded", count=len(mapping))
    return mapping


def segment_for(subreddit: str) -> str:
    """Look up a subreddit (case-insensitive) and return its segment slug."""
    if not subreddit:
        return UNKNOWN_SEGMENT
    return _load_map().get(subreddit.lower(), UNKNOWN_SEGMENT)


def all_segments() -> list[str]:
    """Return the sorted, deduplicated list of segment slugs in the CSV."""
    return sorted({v for v in _load_map().values() if v != UNKNOWN_SEGMENT})


def segment_label(slug: str) -> str:
    """Pretty label for a slug (for UI display when we don't ship the CSV)."""
    if not slug or slug == UNKNOWN_SEGMENT:
        return "Unknown"
    return slug.replace("_", " ").title()


def macro_segment_for(subreddit: str) -> str:
    """Return the macro grouping for a subreddit: 'walmart' or 'competitor'.

    Unknown subreddits default to `DEFAULT_MACRO` ('competitor') so they still
    surface in the comparison view rather than silently disappearing.
    """
    if not subreddit:
        return DEFAULT_MACRO
    return _load_macro_map().get(subreddit.lower(), DEFAULT_MACRO)


def macro_segment_label(macro: str) -> str:
    """Pretty label for a macro slug."""
    return {"walmart": "Walmart", "competitor": "Competitors"}.get(macro, macro.title())
