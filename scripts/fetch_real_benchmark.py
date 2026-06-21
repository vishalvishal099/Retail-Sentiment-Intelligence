"""
Fetch a real, long-form Walmart-Reddit benchmark for human labeling.

Pulls posts from Walmart-core + Spark/last-mile subreddits via the free
Arctic Shift archive (no Reddit API key required). Filters to posts whose
body is long enough that ModernBERT's 8K context window can actually beat
RoBERTa's 512-token cap.

Usage:
    .venv/bin/python scripts/fetch_real_benchmark.py
    .venv/bin/python scripts/fetch_real_benchmark.py --target 200 --min-body 300

Output: data/benchmark_real_200.jsonl (same schema as benchmark_annotations.jsonl
so the existing labeler `scripts/label_benchmark.py --file <path>` works as-is).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingestion.arctic_shift import fetch_posts_arctic  # noqa: E402

SUBREDDITS = [
    # Walmart-core
    ("walmart", 80),
    ("samsclub", 50),
    ("WalmartEmployees", 30),
    ("OGPBackroom", 20),
    # Spark / last-mile (Walmart's gig delivery network)
    ("Sparkdriver", 30),
    ("walmartogp", 10),
]

OUTPUT = Path("data/benchmark_real_200.jsonl")


def fetch_per_sub(sub: str, raw_quota: int, min_body: int, days: int) -> list[dict]:
    """Pull posts and keep only those with body >= min_body chars."""
    print(f"  fetching r/{sub} (target {raw_quota} long-form posts)...", flush=True)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    kept: list[dict] = []
    raw_seen = 0
    # Over-fetch heavily: most posts are short / image / link / removed.
    # `self_posts_only=False` because Arctic Shift's is_self filter returns 0.
    for post in fetch_posts_arctic(sub, since_utc=since, limit=raw_quota * 30, self_posts_only=False):
        raw_seen += 1
        body = (post.get("body") or "").strip()
        if len(body) < min_body:
            continue
        kept.append(post)
        if len(kept) >= raw_quota:
            break
    print(f"    -> kept {len(kept)} / {raw_seen} scanned (min_body={min_body})", flush=True)
    return kept


def score_baseline(rows: list[dict]) -> list[dict]:
    """Run the existing cardiffnlp baseline so the labeler shows useful context."""
    print(f"\nScoring {len(rows)} posts with cardiffnlp baseline (first run downloads ~500MB)...", flush=True)
    from src.analysis.llm_client import HuggingFaceSentimentClient
    from src.utils.config import LLMConfig

    cfg = LLMConfig()  # defaults: cardiffnlp/twitter-roberta-base-sentiment-latest
    client = HuggingFaceSentimentClient(config=cfg)
    texts = [
        ((r.get("title") or "") + "\n\n" + (r.get("body") or "")).strip()[:2000]
        for r in rows
    ]

    out = []
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        results = client.analyze_batch(batch)
        for row, res in zip(rows[i : i + batch_size], results):
            row["_model_sentiment"] = res["sentiment"]
            row["_model_confidence"] = round(res["sentiment_confidence"], 3)
            row["_model_aspects"] = [a["aspect"] for a in res.get("aspects", [])][:3]
            out.append(row)
        print(f"  scored {min(i + batch_size, len(texts))}/{len(texts)}", flush=True)
    return out


def to_annotation_schema(post: dict, idx: int) -> dict:
    """Reshape a fetched post into the labeler's annotation schema."""
    pid = post["id"].replace("reddit_", "")
    return {
        "id": pid,
        "index": idx,
        "subreddit": post["subreddit"],
        "title": post.get("title") or "",
        "body": post.get("body") or "",
        "score": post.get("score", 0),
        "url": post.get("url", ""),
        "human_sentiment": "",
        "human_aspects": [],
        "notes": "",
        # Filled by score_baseline()
        "_model_sentiment": "",
        "_model_confidence": 0.0,
        "_model_aspects": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=200, help="Final post count")
    parser.add_argument("--min-body", type=int, default=300, help="Minimum body length in chars")
    parser.add_argument("--days", type=int, default=730, help="Look back this many days")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-score", action="store_true", help="Skip baseline scoring (much faster)")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"Target: {args.target} real posts, body >= {args.min_body} chars, "
          f"last {args.days} days\n")

    all_kept: list[dict] = []
    for sub, quota in SUBREDDITS:
        all_kept.extend(fetch_per_sub(sub, quota, args.min_body, args.days))

    print(f"\nTotal long-form raw posts: {len(all_kept)}")
    if not all_kept:
        print("ERROR: no posts fetched. Check network or relax --min-body.", file=sys.stderr)
        return 1

    # Shuffle, dedupe by id, take top N
    seen: set[str] = set()
    deduped: list[dict] = []
    random.shuffle(all_kept)
    for p in all_kept:
        pid = p.get("id")
        if pid in seen:
            continue
        seen.add(pid)
        deduped.append(p)
        if len(deduped) >= args.target:
            break

    print(f"After dedup: {len(deduped)} posts kept")
    sub_counts = Counter(p["subreddit"] for p in deduped)
    for s, n in sub_counts.most_common():
        print(f"  r/{s}: {n}")

    annotations = [to_annotation_schema(p, i + 1) for i, p in enumerate(deduped)]

    if not args.no_score:
        annotations = score_baseline(annotations)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in annotations:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    body_lens = [len(r["body"]) for r in annotations]
    print(f"\nWrote {len(annotations)} rows to {args.out}")
    print(f"Body length: min={min(body_lens)}  median={sorted(body_lens)[len(body_lens)//2]}  max={max(body_lens)}")
    if not args.no_score:
        sent_dist = Counter(r["_model_sentiment"] for r in annotations)
        print(f"Baseline sentiment dist: {dict(sent_dist)}")
    print("\nNext step:")
    print(f"  .venv/bin/python scripts/label_benchmark.py --file {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
