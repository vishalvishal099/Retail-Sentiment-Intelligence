"""
Clean the malformed reddit_walmart_communities.csv.
The raw file has two datasets concatenated side-by-side. This script
extracts the left-side columns (the valid data) and writes a clean CSV.
"""

import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "reddit_walmart_communities.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "subreddits_clean.csv"


def clean_csv():
    """Parse the malformed CSV and output a clean version with only usable subreddits."""
    # The raw file is malformed — two CSVs merged horizontally.
    # Left side has: subreddit, group, subscribers, created_utc, subreddit_type, public_description, snapshot_utc, source, notes
    # We extract only the left side and filter to usable subreddits.

    clean_rows = []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    for line in raw_lines:
        # Split on the first 8 commas to get left-side fields
        parts = line.strip().split(",")
        if len(parts) < 6:
            continue

        subreddit = parts[0].strip()
        group = parts[1].strip()
        subscribers_raw = parts[2].strip()
        created_utc = parts[3].strip()
        subreddit_type = parts[4].strip()

        # Skip header row
        if subreddit == "subreddit":
            continue

        # Skip banned, not_found, restricted, or empty subs
        if subreddit_type in ("banned", "not_found", "restricted"):
            continue
        if not subreddit or not subreddit_type:
            continue

        # Parse subscribers
        try:
            subscribers = int(subscribers_raw) if subscribers_raw else 0
        except ValueError:
            subscribers = 0

        # Only keep public subreddits with >100 subscribers (useful for analysis)
        if subreddit_type != "public" or subscribers < 100:
            continue

        clean_rows.append({
            "subreddit": subreddit,
            "group": group,
            "subscribers": subscribers,
            "created_utc": created_utc,
            "subreddit_type": subreddit_type,
        })

    # Sort by subscribers descending
    clean_rows.sort(key=lambda x: x["subscribers"], reverse=True)

    # Write clean CSV
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["subreddit", "group", "subscribers", "created_utc", "subreddit_type"])
        writer.writeheader()
        writer.writerows(clean_rows)

    print(f"✓ Cleaned {len(clean_rows)} subreddits → {OUTPUT_FILE}")
    for row in clean_rows:
        print(f"  r/{row['subreddit']:25s} ({row['group']:25s}) — {row['subscribers']:>10,} subscribers")


if __name__ == "__main__":
    clean_csv()
