"""
Retail Sentiment Intelligence — Duplicate Detector
Uses content hashing + optional sentence embeddings for near-duplicate detection.
"""

import hashlib
import re
from collections import defaultdict

from src.utils.logger import get_logger

log = get_logger("trust_dedup")

# In-memory store of recent content hashes for near-dedup
_recent_hashes: dict[str, int] = defaultdict(int)  # hash -> count


def score_originality(unit: dict) -> float:
    """
    Score originality (0.0 = likely duplicate/spam, 1.0 = unique).
    Uses normalized content hashing for fast dedup.
    """
    text = _get_text(unit)
    if not text:
        return 0.0

    # Normalize and hash
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    content_hash = hashlib.md5(normalized.encode()).hexdigest()

    # Check how many times we've seen similar content
    _recent_hashes[content_hash] += 1
    count = _recent_hashes[content_hash]

    if count == 1:
        return 1.0  # First time seeing this content
    elif count == 2:
        return 0.5  # Seen once before
    elif count <= 5:
        return 0.2  # Seen multiple times
    else:
        return 0.0  # Likely spam/bot

def reset_dedup_store():
    """Reset dedup store (call between evaluation cycles if needed)."""
    global _recent_hashes
    _recent_hashes = defaultdict(int)


def _get_text(unit: dict) -> str:
    title = unit.get("title", "") or ""
    body = unit.get("body", "") or ""
    return f"{title} {body}".strip()
