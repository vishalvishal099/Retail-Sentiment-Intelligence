"""
Retail Sentiment Intelligence — Subreddit Registry
====================================================
Read/write API for the editable list of subreddits the pipeline pulls from.
Backed by data/subreddits_clean.csv. Adds an optional `enabled` column
(default: true) so the UI can toggle subs on/off without losing the entry.

Why a tiny module instead of inlining in api.py:
  • the pipeline itself (src/pipeline.py) wants to filter the same list
  • tests want to exercise CRUD without booting FastAPI
  • CSV writes need to be atomic-ish (temp file + rename)
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.utils.logger import get_logger
from src.utils.segments import segment_for, _slugify, macro_segment_for, MACRO_GROUPS, DEFAULT_MACRO

log = get_logger("subreddit_registry")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "subreddits_clean.csv"

# Canonical column order — anything we write goes back in this order so the
# file stays diffable. New columns are appended.
COLUMNS = ["subreddit", "group", "macro_group", "subscribers", "created_utc", "subreddit_type", "enabled"]


@dataclass
class SubredditEntry:
    subreddit: str
    group: str
    subscribers: int
    created_utc: str
    subreddit_type: str
    enabled: bool
    macro_group: str = DEFAULT_MACRO

    @property
    def segment(self) -> str:
        return _slugify(self.group)

    def to_row(self) -> dict:
        return {
            "subreddit": self.subreddit,
            "group": self.group,
            "macro_group": self.macro_group if self.macro_group in MACRO_GROUPS else DEFAULT_MACRO,
            "subscribers": str(self.subscribers) if self.subscribers else "",
            "created_utc": self.created_utc or "",
            "subreddit_type": self.subreddit_type or "public",
            "enabled": "true" if self.enabled else "false",
        }


def _truthy(v) -> bool:
    if v is None or v == "":
        return True  # default: enabled when column missing
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y", "t")


def load_all(csv_path: Path | str = DEFAULT_CSV) -> list[SubredditEntry]:
    p = Path(csv_path)
    if not p.exists():
        return []
    entries: list[SubredditEntry] = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sub = (row.get("subreddit") or "").strip()
            if not sub:
                continue
            try:
                subs = int(row.get("subscribers") or 0)
            except (TypeError, ValueError):
                subs = 0
            entries.append(SubredditEntry(
                subreddit=sub,
                group=(row.get("group") or "").strip(),
                subscribers=subs,
                created_utc=(row.get("created_utc") or "").strip(),
                subreddit_type=(row.get("subreddit_type") or "public").strip(),
                enabled=_truthy(row.get("enabled")),
                macro_group=(
                    (row.get("macro_group") or "").strip().lower()
                    if (row.get("macro_group") or "").strip().lower() in MACRO_GROUPS
                    else macro_segment_for(sub)
                ),
            ))
    return entries


def load_enabled_names(csv_path: Path | str = DEFAULT_CSV) -> list[str]:
    """Just the names of subs the pipeline should pull from."""
    return [e.subreddit for e in load_all(csv_path) if e.enabled]


def save_all(entries: Iterable[SubredditEntry], csv_path: Path | str = DEFAULT_CSV) -> None:
    """Atomic write: temp file in same dir + rename."""
    p = Path(csv_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # write to sibling temp file so rename is atomic on POSIX
    fd, tmp_path = tempfile.mkstemp(prefix=".registry.", suffix=".csv", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for e in entries:
                writer.writerow(e.to_row())
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def set_enabled(subreddits: dict[str, bool], csv_path: Path | str = DEFAULT_CSV) -> dict:
    """Flip enabled flags. `subreddits` is {name: enabled}. Names not present
    in the CSV are ignored (use upsert() to add new ones)."""
    entries = load_all(csv_path)
    name_to_target = {k.lower(): v for k, v in subreddits.items()}
    changed = []
    for e in entries:
        new_val = name_to_target.get(e.subreddit.lower())
        if new_val is not None and e.enabled != bool(new_val):
            e.enabled = bool(new_val)
            changed.append((e.subreddit, e.enabled))
    save_all(entries, csv_path)
    log.info("subreddit_enabled_updated", count=len(changed))
    return {"updated": len(changed), "changes": changed}


def upsert(name: str, group: str = "", enabled: bool = True,
           subscribers: int = 0, subreddit_type: str = "public",
           csv_path: Path | str = DEFAULT_CSV) -> SubredditEntry:
    """Add a new subreddit OR update its group/enabled. Idempotent."""
    name = name.strip().lstrip("r/").lstrip("/")
    assert name, "subreddit name required"
    entries = load_all(csv_path)
    by_lower = {e.subreddit.lower(): e for e in entries}
    if name.lower() in by_lower:
        e = by_lower[name.lower()]
        if group:
            e.group = group
        e.enabled = enabled
        result = e
    else:
        # Infer group from the segment helper if caller didn't pass one — that
        # at least gives us "unknown" rather than a missing slug.
        if not group:
            group = segment_for(name)
        result = SubredditEntry(
            subreddit=name, group=group, subscribers=subscribers,
            created_utc="", subreddit_type=subreddit_type, enabled=enabled,
            macro_group=macro_segment_for(name),
        )
        entries.append(result)
    save_all(entries, csv_path)
    log.info("subreddit_upserted", name=name, enabled=enabled, group=group)
    return result


def remove(name: str, csv_path: Path | str = DEFAULT_CSV) -> bool:
    """Hard-delete a subreddit from the registry. Returns True if removed."""
    name_l = name.strip().lstrip("r/").lstrip("/").lower()
    entries = load_all(csv_path)
    new_entries = [e for e in entries if e.subreddit.lower() != name_l]
    if len(new_entries) == len(entries):
        return False
    save_all(new_entries, csv_path)
    log.info("subreddit_removed", name=name)
    return True
