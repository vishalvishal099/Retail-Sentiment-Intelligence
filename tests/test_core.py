"""
Tests for trust scorer, preprocessor, and storage.
"""

import pytest
from src.trust.heuristics import score_metadata
from src.trust.dedup import score_originality, reset_dedup_store
from src.ingestion.preprocess import preprocess_unit, reset_dedup_cache
from src.utils.privacy import hash_username


class TestTrustHeuristics:
    def test_established_account_high_score(self):
        unit = {
            "body": "I've been working at Walmart for 5 years and the scheduling system is terrible.",
            "score": 25,
            "author_metadata": {
                "account_age_days": 1200,
                "total_karma": 8000,
            }
        }
        score = score_metadata(unit)
        assert score >= 0.7

    def test_new_account_low_score(self):
        unit = {
            "body": "Wow!",
            "score": 0,
            "author_metadata": {
                "account_age_days": 2,
                "total_karma": 5,
            }
        }
        score = score_metadata(unit)
        assert score <= 0.3

    def test_score_bounds(self):
        unit = {"body": "test", "score": 0, "author_metadata": {"account_age_days": 0, "total_karma": 0}}
        score = score_metadata(unit)
        assert 0.0 <= score <= 1.0


class TestDedupScorer:
    def setup_method(self):
        reset_dedup_store()

    def test_first_occurrence_is_original(self):
        unit = {"title": "Test post", "body": "This is unique content"}
        score = score_originality(unit)
        assert score == 1.0

    def test_duplicate_gets_low_score(self):
        unit = {"title": "Test post", "body": "This is duplicate content"}
        score_originality(unit)  # first
        score = score_originality(unit)  # duplicate
        assert score <= 0.5


class TestPreprocessor:
    def setup_method(self):
        reset_dedup_cache()

    def test_filters_empty_content(self):
        unit = {"title": "", "body": ""}
        result = preprocess_unit(unit, english_only=False)
        assert result is None

    def test_filters_deleted(self):
        unit = {"title": "test", "body": "[deleted]"}
        result = preprocess_unit(unit, english_only=False)
        assert result is None

    def test_keeps_valid_content(self):
        unit = {"title": "My walmart experience", "body": "This was a really great shopping trip today at store 1234."}
        result = preprocess_unit(unit, english_only=False)
        assert result is not None
        assert "content_hash" in result


class TestPrivacy:
    def test_hash_is_deterministic(self):
        assert hash_username("testuser") == hash_username("testuser")

    def test_hash_is_different_per_user(self):
        assert hash_username("user1") != hash_username("user2")

    def test_hash_is_not_reversible(self):
        hashed = hash_username("testuser")
        assert "testuser" not in hashed
