"""
Retail Sentiment Intelligence — Trust Metadata Heuristics
Scores post/comment credibility based on author metadata and linguistic signals.
"""

import re
from typing import Optional

from src.utils.config import TrustConfig
from src.utils.logger import get_logger

log = get_logger("trust_heuristics")


_PROMO_PHRASES = re.compile(
    r"\b(buy now|click here|limited time|act fast|don'?t miss|free shipping|"
    r"promo code|coupon code|discount code|deal of the day|hot deal|"
    r"check (?:out )?my (?:bio|profile|link)|dm me|message me for|"
    r"link in (?:bio|comments)|sign up now|register now|use code)\b",
    re.IGNORECASE,
)

# Walmart/retail-specific insider terminology — strong authenticity signal.
_RETAIL_SPECIFIC_TERMS = re.compile(
    r"\b(asm|tle?|csm|gm|coach|associate|cap[\s\-]?2|fresh|deli|"
    r"ogp|spark|onepos|gta|atlas|me@walmart|sam'?s club|"
    r"walmart\+?|store\s+\d+|aisle\s+\d+|department\s+\d+|register\s+\d+)\b",
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")


def score_metadata(unit: dict, config: Optional[TrustConfig] = None) -> float:
    """
    Score credibility based on author metadata (0.0–1.0).

    Combines: account age, total karma, content length, engagement, plus a
    `base` floor so a brand-new short post still has a reasonable baseline.
    Weights and the floor are configurable in `config/pipeline_config.yaml`
    under `trust.metadata_weights`.
    """
    meta = unit.get("author_metadata", {}) or {}
    account_age_days = meta.get("account_age_days", 0) or 0
    total_karma = meta.get("total_karma", 0) or 0
    body = unit.get("body", "") or ""
    title = unit.get("title", "") or ""
    score_val = unit.get("score", 0) or 0

    # Per-signal scores, each clamped to [0, 1].
    age_score = min(account_age_days / 365.0, 1.0)
    karma_score = min(total_karma / 5000.0, 1.0)
    # Length over (title + body) so headline-only posts aren't unfairly penalised.
    text_len = len(title) + len(body)
    length_score = min(text_len / 200.0, 1.0)
    engagement_score = min(max(score_val, 0) / 20.0, 1.0)

    if config is not None:
        w_age = config.metadata_weight_age
        w_karma = config.metadata_weight_karma
        w_length = config.metadata_weight_length
        w_eng = config.metadata_weight_engagement
        w_base = config.metadata_weight_base
    else:
        # Backwards-compatible defaults (used by tests that build units directly).
        w_age, w_karma, w_length, w_eng, w_base = 0.20, 0.20, 0.30, 0.15, 0.15

    combined = (
        w_base
        + w_age * age_score
        + w_karma * karma_score
        + w_length * length_score
        + w_eng * engagement_score
    )
    return round(min(max(combined, 0.0), 1.0), 3)


def score_credibility(unit: dict) -> tuple[float, list[str]]:
    """
    Score author/content credibility (0.0–1.0) using rule-based heuristics.

    Complements `score_metadata` by examining linguistic and behavioural
    markers — promotional spam phrases, URL stuffing, excessive caps,
    karma-vs-age anomalies (negative signals), and retail-specific insider
    terminology / organic long-form text (positive signals).

    Returns (score, flags) where flags is a list of triggered indicators.
    """
    title = unit.get("title", "") or ""
    body = unit.get("body", "") or ""
    text = f"{title} {body}".strip()
    meta = unit.get("author_metadata", {}) or {}

    flags: list[str] = []

    if not text:
        return 0.3, ["empty_content"]

    text_len = len(text)
    letters = [c for c in text if c.isalpha()]
    caps_ratio = sum(1 for c in letters if c.isupper()) / max(len(letters), 1)
    excl_per_100 = text.count("!") / max(text_len / 100.0, 1.0)
    url_count = len(_URL_PATTERN.findall(text))
    promo_hits = len(_PROMO_PHRASES.findall(text))
    specific_hits = len(_RETAIL_SPECIFIC_TERMS.findall(text))

    account_age_days = meta.get("account_age_days", 0) or 0
    total_karma = meta.get("total_karma", 0) or 0

    score = 0.5  # neutral baseline

    # ---- Negative signals ----
    if promo_hits >= 2:
        score -= 0.25
        flags.append("promotional_language")
    elif promo_hits == 1:
        score -= 0.10
        flags.append("mild_promotional")

    if url_count >= 3 and text_len < 500:
        score -= 0.20
        flags.append("url_stuffing")
    elif url_count >= 1 and text_len < 100:
        score -= 0.10
        flags.append("link_only_post")

    if caps_ratio > 0.40 and len(letters) > 30:
        score -= 0.15
        flags.append("excessive_caps")

    if excl_per_100 > 4:
        score -= 0.10
        flags.append("excessive_exclamation")

    if account_age_days and account_age_days < 30 and total_karma > 1000:
        # New account with disproportionate karma — purchased or farmed.
        score -= 0.20
        flags.append("karma_age_mismatch")

    if account_age_days and account_age_days < 7 and promo_hits >= 1:
        score -= 0.20
        flags.append("new_account_promotional")

    # ---- Positive signals ----
    if specific_hits >= 2:
        score += 0.25
        flags.append("retail_specific_detail")
    elif specific_hits == 1:
        score += 0.10
        flags.append("some_retail_detail")

    if text_len > 200 and url_count == 0 and promo_hits == 0:
        score += 0.10
        flags.append("organic_long_form")

    score = round(min(max(score, 0.0), 1.0), 3)
    return score, flags
