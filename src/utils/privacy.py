"""
Retail Sentiment Intelligence — Privacy Utilities
Hashes usernames per R6 requirement.
"""

import hashlib


def hash_username(username: str, salt: str = "rsi_v1") -> str:
    """One-way hash of Reddit username. Not reversible."""
    return hashlib.sha256(f"{salt}:{username}".encode()).hexdigest()[:16]
