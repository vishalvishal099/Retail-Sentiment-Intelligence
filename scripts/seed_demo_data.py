"""Seed the local SQLite database with realistic demo data for dashboard testing."""

import json
import random
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "local.db"

SUBREDDITS = ["walmart", "samsclub", "grocery", "retailhell", "frugal"]
ASPECTS = ["pricing", "customer_service", "product_quality", "store_experience", "online_ordering", "delivery", "returns"]
SENTIMENTS = ["positive", "negative", "neutral"]

SAMPLE_TEXTS = {
    "positive": [
        "Walmart+ delivery has been amazing lately. Got my groceries in under 2 hours!",
        "Great deals on electronics this week. Saved over $200 on a TV.",
        "The new self-checkout is actually really fast and convenient.",
        "Sam's Club rotisserie chicken is the best value anywhere.",
        "Online pickup is so smooth now. In and out in 5 minutes.",
        "Customer service was incredibly helpful with my return today.",
        "Their Great Value brand keeps getting better. Some items rival name brands.",
        "Love the scan & go app at Sam's Club. No lines ever!",
    ],
    "negative": [
        "Waited 45 minutes for a pickup order that was supposed to be ready. Terrible.",
        "Prices keep going up but quality keeps going down. Very frustrating.",
        "The app crashed three times while I was trying to place an order.",
        "Store was filthy and half the shelves were empty. Unacceptable.",
        "Got a damaged item delivered and the return process is a nightmare.",
        "Self-checkout had 2 out of 8 machines working. Line was insane.",
        "Customer service rep was incredibly rude. Will not be going back.",
        "Delivery driver left my frozen food on the porch in 95 degree heat.",
    ],
    "neutral": [
        "Does anyone know if Walmart price matches with Amazon?",
        "What time does the pharmacy close on weekends?",
        "Thinking about getting a Sam's Club membership. Worth it for a family of 4?",
        "The store layout changed again. Took me forever to find anything.",
        "Comparing Walmart+ vs Amazon Prime for grocery delivery.",
        "New store opening in our area next month apparently.",
    ],
}


def seed():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Create tables if needed (same as store.py)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_posts (
            id TEXT PRIMARY KEY, subreddit TEXT, data JSON NOT NULL,
            created_timestamp REAL, processing_status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY, post_id TEXT, subreddit TEXT, data JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS aggregates (
            id TEXT PRIMARY KEY, time_window TEXT, window_type TEXT, data JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY, type TEXT, severity TEXT, time_window TEXT, data JSON NOT NULL
        );
    """)

    now = datetime.now(timezone.utc)
    posts = []
    analyses = []

    # Generate 14 days of posts (50-80 per day)
    for day_offset in range(14):
        day = now - timedelta(days=day_offset)
        day_str = day.strftime("%Y-%m-%d")
        num_posts = random.randint(50, 80)

        day_sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        day_aspect_counts = {a: 0 for a in ASPECTS}
        day_subreddit_counts = {s: 0 for s in SUBREDDITS}

        for i in range(num_posts):
            post_id = str(uuid.uuid4())[:12]
            subreddit = random.choice(SUBREDDITS)
            sentiment = random.choices(SENTIMENTS, weights=[0.45, 0.30, 0.25])[0]
            trust_score = round(random.uniform(0.3, 0.98), 3)
            is_trusted = trust_score >= 0.5
            post_aspects = random.sample(ASPECTS, k=random.randint(1, 3))
            text = random.choice(SAMPLE_TEXTS[sentiment])
            created_ts = (day - timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))).timestamp()

            post_data = {
                "id": post_id,
                "subreddit": subreddit,
                "title": text[:60],
                "body": text,
                "author": f"user_{random.randint(1000, 9999)}",
                "score": random.randint(-5, 500),
                "created_timestamp": created_ts,
                "trust_score": trust_score,
                "is_trusted": is_trusted,
                "sentiment": sentiment,
                "aspects": [{"aspect": a, "confidence": round(random.uniform(0.6, 0.95), 2)} for a in post_aspects],
                "partition_key": subreddit,
            }
            posts.append((post_id, subreddit, json.dumps(post_data), created_ts, "analyzed"))

            # Analysis record
            confidence = round(random.uniform(0.65, 0.98), 3)
            needs_review = 1 if confidence < 0.75 else 0
            analysis_data = {
                "id": f"an_{post_id}",
                "post_id": post_id,
                "subreddit": subreddit,
                "sentiment": sentiment,
                "sentiment_confidence": confidence,
                "aspects": post_aspects,
                "trust_score": trust_score,
                "is_trusted": is_trusted,
                "needs_review": needs_review,
                "analyzed_at": day.isoformat(),
                "model": "cardiffnlp/twitter-roberta-base-sentiment-latest",
                "partition_key": subreddit,
            }
            analyses.append((f"an_{post_id}", post_id, subreddit, json.dumps(analysis_data)))

            day_sentiment_counts[sentiment] += 1
            for a in post_aspects:
                day_aspect_counts[a] += 1
            day_subreddit_counts[subreddit] += 1

        # Daily aggregate
        trusted_count = sum(1 for p in posts[-num_posts:] if json.loads(p[2]).get("is_trusted"))
        agg_data = {
            "id": f"agg_{day_str}_daily",
            "time_window": day_str,
            "window_type": "daily",
            "total_posts": num_posts,
            "trusted_posts": trusted_count,
            "sentiment_distribution": day_sentiment_counts,
            "aspect_breakdown": day_aspect_counts,
            "subreddit_distribution": day_subreddit_counts,
            "avg_trust_score": round(random.uniform(0.6, 0.8), 3),
            "partition_key": day_str,
        }
        conn.execute(
            "INSERT OR REPLACE INTO aggregates (id, time_window, window_type, data) VALUES (?, ?, ?, ?)",
            (f"agg_{day_str}_daily", day_str, "daily", json.dumps(agg_data))
        )

    # Insert posts and analyses
    conn.executemany(
        "INSERT OR REPLACE INTO raw_posts (id, subreddit, data, created_timestamp, processing_status) VALUES (?, ?, ?, ?, ?)",
        posts
    )
    conn.executemany(
        "INSERT OR REPLACE INTO analyses (id, post_id, subreddit, data) VALUES (?, ?, ?, ?)",
        analyses
    )

    # Insert some alerts
    alert_types = [
        ("volume_spike", "warning", "Post volume 2.3x above normal in r/walmart"),
        ("sentiment_crash", "critical", "Negative sentiment jumped 40% in last 6 hours"),
        ("emerging_topic", "info", "New topic cluster detected: 'delivery delays' across 3 subreddits"),
    ]
    today_str = now.strftime("%Y-%m-%d")
    for atype, severity, message in alert_types:
        alert_id = f"alert_{atype}_{today_str}"
        alert_data = {
            "id": alert_id,
            "type": atype,
            "severity": severity,
            "message": message,
            "time_window": today_str,
            "detected_at": now.isoformat(),
            "acknowledged": False,
            "partition_key": today_str,
        }
        conn.execute(
            "INSERT OR REPLACE INTO alerts (id, type, severity, time_window, data) VALUES (?, ?, ?, ?, ?)",
            (alert_id, atype, severity, today_str, json.dumps(alert_data))
        )

    conn.commit()
    conn.close()

    total_posts = len(posts)
    total_analyses = len(analyses)
    print(f"Seeded {total_posts} posts, {total_analyses} analyses, 14 daily aggregates, 3 alerts into {DB_PATH}")


if __name__ == "__main__":
    seed()
