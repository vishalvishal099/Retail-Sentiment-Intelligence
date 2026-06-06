"""
Comprehensive integration test — validates the full pipeline flow
end-to-end without requiring external APIs (uses mock data).
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.store import SQLiteBackend
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine
from src.ingestion.preprocess import preprocess_units, reset_dedup_cache
from src.trust.heuristics import score_metadata
from src.trust.dedup import score_originality, reset_dedup_store
from src.utils.privacy import hash_username


def test_full_flow():
    """End-to-end test: ingest → preprocess → trust → store → aggregate → alert."""
    db_path = "data/test_e2e.db"
    db = SQLiteBackend(db_path)
    reset_dedup_cache()
    reset_dedup_store()

    # --- Stage 1: Simulate ingestion (mock Reddit posts) ---
    mock_posts = [
        {"id": "post_001", "title": "Walmart prices are insane", "body": "Everything costs double now. Frustrated.",
         "subreddit": "walmart", "author": "user_a", "score": 42, "created_timestamp": datetime.now(timezone.utc).timestamp(),
         "unit_type": "post", "author_metadata": {"account_age_days": 500, "total_karma": 3000}},
        {"id": "post_002", "title": "Great experience at Sam's Club", "body": "Love the bulk deals. Staff was helpful.",
         "subreddit": "samsclub", "author": "user_b", "score": 18, "created_timestamp": datetime.now(timezone.utc).timestamp(),
         "unit_type": "post", "author_metadata": {"account_age_days": 1200, "total_karma": 8000}},
        {"id": "post_003", "title": "", "body": "[deleted]",
         "subreddit": "walmart", "author": "[deleted]", "score": 0, "created_timestamp": datetime.now(timezone.utc).timestamp(),
         "unit_type": "post", "author_metadata": {"account_age_days": 0, "total_karma": 0}},
        {"id": "post_004", "title": "Walmart+ delivery late again", "body": "Third time this month my order arrived late.",
         "subreddit": "walmart", "author": "user_c", "score": 67, "created_timestamp": datetime.now(timezone.utc).timestamp(),
         "unit_type": "post", "author_metadata": {"account_age_days": 800, "total_karma": 5000}},
        {"id": "post_005", "title": "New Walmart opened nearby", "body": "A new supercenter opened on Main St.",
         "subreddit": "walmart", "author": "user_d", "score": 5, "created_timestamp": datetime.now(timezone.utc).timestamp(),
         "unit_type": "post", "author_metadata": {"account_age_days": 30, "total_karma": 100}},
    ]
    print(f"Stage 1: Ingested {len(mock_posts)} mock posts")

    # --- Stage 2: Preprocess ---
    clean = preprocess_units(mock_posts, english_only=True)
    assert len(clean) == 4, f"Expected 4 after filtering [deleted], got {len(clean)}"
    print(f"Stage 2: Preprocessed → {len(clean)} clean units")

    # --- Stage 3: Trust scoring ---
    for unit in clean:
        trust = score_metadata(unit)
        originality = score_originality(unit)
        unit["trust_score"] = round(0.7 * trust + 0.3 * originality, 3)
        unit["is_trusted"] = unit["trust_score"] >= 0.4
    trusted = [u for u in clean if u["is_trusted"]]
    flagged = [u for u in clean if not u["is_trusted"]]
    print(f"Stage 3: Trust scored → {len(trusted)} trusted, {len(flagged)} flagged")

    # --- Stage 4: Store ---
    db.upsert_batch("raw_posts", clean)
    stored = db.get_item("raw_posts", "post_001", "")
    assert stored is not None
    print(f"Stage 4: Stored {len(clean)} posts in SQLite")

    # --- Stage 5: Mock analysis (simulating HF model output) ---
    now_iso = datetime.now(timezone.utc).isoformat()
    analyses = [
        {"id": "analysis_post_001", "post_id": "post_001", "subreddit": "walmart",
         "sentiment": "negative", "sentiment_confidence": 0.92, "needs_review": False,
         "aspects": [{"aspect": "pricing", "sentiment": "negative", "confidence": 0.85}],
         "trust_score": 0.8, "analyzed_at": now_iso},
        {"id": "analysis_post_002", "post_id": "post_002", "subreddit": "samsclub",
         "sentiment": "positive", "sentiment_confidence": 0.88, "needs_review": False,
         "aspects": [{"aspect": "customer service", "sentiment": "positive", "confidence": 0.7}],
         "trust_score": 0.9, "analyzed_at": now_iso},
        {"id": "analysis_post_004", "post_id": "post_004", "subreddit": "walmart",
         "sentiment": "negative", "sentiment_confidence": 0.95, "needs_review": False,
         "aspects": [{"aspect": "delivery/pickup", "sentiment": "negative", "confidence": 0.9}],
         "trust_score": 0.85, "analyzed_at": now_iso},
        {"id": "analysis_post_005", "post_id": "post_005", "subreddit": "walmart",
         "sentiment": "neutral", "sentiment_confidence": 0.55, "needs_review": True,
         "aspects": [{"aspect": "store experience", "sentiment": "neutral", "confidence": 0.4}],
         "trust_score": 0.5, "analyzed_at": now_iso},
    ]
    db.upsert_batch("analyses", analyses)
    print(f"Stage 5: Analyzed {len(analyses)} posts")

    # --- Stage 6: Aggregation ---
    agg = Aggregator(db)
    result = agg.aggregate_window("daily")
    assert result != {}
    assert result["total_posts"] == 4
    assert result["sentiment_distribution"]["negative"] == 0.5  # 2/4
    assert "pricing" in result["aspect_breakdown"]
    print(f"Stage 6: Aggregated → {result['total_posts']} posts, sentiment: {result['sentiment_distribution']}")

    # --- Stage 7: Alert detection ---
    alert_engine = AlertEngine(db)
    alerts = alert_engine.detect_all()
    # No baseline data so no alerts expected
    print(f"Stage 7: Alerts detected → {len(alerts)} (none expected without 7-day history)")

    # --- Stage 8: Review queue ---
    review_query = "SELECT data FROM analyses WHERE json_extract(data, '$.needs_review') = 1"
    review_items = db.query("analyses", review_query, [])
    assert len(review_items) == 1
    assert review_items[0]["post_id"] == "post_005"
    print(f"Stage 8: Review queue → {len(review_items)} items pending")

    # --- Stage 9: HITL Feedback ---
    feedback = {
        "id": "fb_post_005_001",
        "post_id": "post_005",
        "analyst_id": "reviewer_1",
        "original_sentiment": "neutral",
        "corrected_sentiment": "positive",
        "created_at": now_iso,
        "partition_key": "reviewer_1",
    }
    db.upsert("feedback", feedback)
    stored_fb = db.get_item("feedback", "fb_post_005_001", "")
    assert stored_fb is not None
    print(f"Stage 9: HITL feedback stored")

    # --- Stage 10: Privacy ---
    h1 = hash_username("user_a")
    h2 = hash_username("user_b")
    assert h1 != h2
    assert "user_a" not in h1
    print(f"Stage 10: Privacy hashing works (user_a → {h1[:8]}...)")

    # --- Dashboard API Test ---
    from src.dashboard.api import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    endpoints = ["/health", "/api/brand-health", "/api/alerts", "/api/review", "/api/aspects", "/api/posts", "/api/trust-stats"]
    for ep in endpoints:
        r = client.get(ep)
        assert r.status_code == 200, f"{ep} returned {r.status_code}"
    print(f"Dashboard: All {len(endpoints)} API endpoints → 200 OK")

    # Cleanup
    db.close()
    os.remove(db_path)

    print()
    print("=" * 50)
    print("FULL E2E INTEGRATION TEST: ALL STAGES PASSED")
    print("=" * 50)


if __name__ == "__main__":
    test_full_flow()
