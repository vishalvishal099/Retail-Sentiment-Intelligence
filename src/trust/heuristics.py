"""
Retail Sentiment Intelligence — Trust Metadata Heuristics
Scores post/comment credibility based on author metadata.
"""

from src.utils.logger import get_logger

log = get_logger("trust_heuristics")


def score_metadata(unit: dict) -> float:
    """
    Score credibility based on author metadata (0.0–1.0).

    Factors:
    - Account age (older = more trustworthy)
    - Total karma (higher = more engaged)
    - Post has specific details (longer = more likely genuine)
    """
    meta = unit.get("author_metadata", {})
    account_age_days = meta.get("account_age_days", 0)
    total_karma = meta.get("total_karma", 0)
    body = unit.get("body", "") or ""
    score_val = unit.get("score", 0)

    # Account age score (0-1): ramp from 0 to 1 over 365 days
    age_score = min(account_age_days / 365.0, 1.0)

    # Karma score (0-1): ramp from 0 to 1 over 5000 karma
    karma_score = min(total_karma / 5000.0, 1.0)

    # Content specificity: longer posts tend to be more genuine
    length_score = min(len(body) / 200.0, 1.0)

    # Engagement: positive score indicates community finds it valuable
    engagement_score = min(max(score_val, 0) / 20.0, 1.0)

    # Weighted combination
    combined = (
        0.30 * age_score +
        0.25 * karma_score +
        0.25 * length_score +
        0.20 * engagement_score
    )

    return round(min(max(combined, 0.0), 1.0), 3)
