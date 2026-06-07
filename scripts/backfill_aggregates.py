"""Backfill daily aggregates for all days that have analyses in storage."""
import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone, timedelta
from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.storage.store import create_storage
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine

setup_logging()
log = get_logger("backfill_agg")

cfg = load_config()
storage = create_storage(cfg.storage)
agg = Aggregator(storage)

# Determine date range from analyses
import sqlite3, json
conn = sqlite3.connect(cfg.storage.sqlite_path)
rows = conn.execute("""
    SELECT DISTINCT DATE(json_extract(data, '$.analyzed_at')) as day
    FROM analyses
    WHERE json_extract(data, '$.analyzed_at') IS NOT NULL
    ORDER BY day ASC
""").fetchall()
conn.close()

days = [r[0] for r in rows if r[0]]
print(f"Found {len(days)} days with analyses: {days[0]} → {days[-1]}")

computed = 0
for day_str in days:
    target = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    result = agg.aggregate_window("daily", target_date=target)
    if result:
        computed += 1
        tp = result.get("total_posts", 0)
        print(f"  {day_str}: {tp} posts aggregated")

print(f"\nDone. Computed {computed} daily aggregates.")

# Run alert detection
engine = AlertEngine(storage)
alerts = engine.detect_all()
for a in alerts:
    storage.upsert("alerts", a)
print(f"Generated {len(alerts)} alerts.")
