"""Quick test of Arctic Shift fetcher."""
import sys
sys.path.insert(0, '.')
from src.ingestion.arctic_shift import fetch_posts_arctic

posts = list(fetch_posts_arctic("walmart", limit=5))
print(f"Fetched {len(posts)} real posts from r/walmart:\n")
for p in posts:
    title = p["title"][:70]
    pid = p["id"]
    score = p["score"]
    url = p["url"]
    body = (p["body"] or "")[:100]
    print(f"  [{pid}] {title}")
    if body:
        print(f"    body: {body}")
    print(f"    score={score}  url={url}")
    print()
