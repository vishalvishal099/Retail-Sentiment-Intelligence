"""
Retail Sentiment Intelligence — Trust Metadata Heuristics
Scores post/comment credibility based on author metadata.
"""

from typing import Optional

from src.utils.config import TrustConfig
from src.utils.logger import get_logger

log = get_logger("trust_heuristics")


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
