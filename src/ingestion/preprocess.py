"""
Retail Sentiment Intelligence — Preprocessor
Cleans, deduplicates, and filters ingested posts/comments.
"""

import hashlib
import re
from typing import Optional

from langdetect import detect, LangDetectException

from src.utils.logger import get_logger

log = get_logger("preprocess")

# Set of seen content hashes for deduplication within a cycle
_seen_hashes: set = set()


def preprocess_units(units: list[dict], english_only: bool = True) -> list[dict]:
    """
    Clean, deduplicate, and filter a batch of posts/comments.
    Returns only units that pass all filters.
    """
    clean = []
    for unit in units:
        processed = preprocess_unit(unit, english_only=english_only)
        if processed is not None:
            clean.append(processed)

    log.info("preprocess_complete", input_count=len(units), output_count=len(clean),
             filtered=len(units) - len(clean))
    return clean


def preprocess_unit(unit: dict, english_only: bool = True) -> Optional[dict]:
    """Process a single unit. Returns None if it should be filtered out."""
    text = _get_text(unit)

    # Filter: empty content
    if not text or len(text.strip()) < 10:
        return None

    # Filter: deleted/removed
    body = unit.get("body", "") or ""
    if body.strip().lower() in ("[deleted]", "[removed]"):
        return None

    # Filter: English only
    if english_only and not _is_english(text):
        return None

    # Deduplicate by content hash
    content_hash = _content_hash(text)
    if content_hash in _seen_hashes:
        return None
    _seen_hashes.add(content_hash)

    # Clean text (preserve sentiment cues like caps, punctuation)
    unit["body"] = _clean_text(unit.get("body", ""))
    if unit.get("title"):
        unit["title"] = _clean_text(unit["title"])

    # Add content hash for future dedup
    unit["content_hash"] = content_hash

    return unit


def reset_dedup_cache():
    """Reset the dedup cache between cycles."""
    global _seen_hashes
    _seen_hashes = set()


def _get_text(unit: dict) -> str:
    """Get the full text content of a unit."""
    title = unit.get("title", "") or ""
    body = unit.get("body", "") or ""
    return f"{title} {body}".strip()


def _content_hash(text: str) -> str:
    """Generate a hash for deduplication."""
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.md5(normalized.encode()).hexdigest()


def _is_english(text: str) -> bool:
    """Detect if text is English."""
    try:
        return detect(text) == "en"
    except LangDetectException:
        return False


def _clean_text(text: str) -> str:
    """
    Clean text while preserving sentiment cues.
    - Remove URLs
    - Remove Reddit formatting artifacts
    - Normalize whitespace
    - Keep caps, punctuation, emojis (they carry sentiment)
    """
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove Reddit markdown links [text](url)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove excessive Reddit formatting
    text = re.sub(r"[*_~]{2,}", "", text)
    # Remove quote markers
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
