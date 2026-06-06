"""Analyze raw_posts that have a trust_score but no corresponding analyses row.

Useful after an ingest+trust run that didn't make it through the analyze stage.
"""
import json
import sys
sys.path.insert(0, ".")

from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.utils.cost_tracker import CostTracker
from src.storage.store import create_storage
from src.analysis.llm_client import create_llm_client
from src.analysis.analyzer import SentimentAnalyzer
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine

import sqlite3

setup_logging()
log = get_logger("analyze_existing")

cfg = load_config()
storage = create_storage(cfg.storage)
cost = CostTracker(log_file=cfg.llm.cost_log_file, daily_limit_usd=cfg.llm.daily_limit_usd)
llm = create_llm_client(cfg.llm, cost)
analyzer = SentimentAnalyzer(llm, cfg.analysis)

# Load trusted real raw posts that have no analysis row yet
db = sqlite3.connect(cfg.storage.sqlite_path)
existing_analyses = {row[0] for row in db.execute("SELECT id FROM analyses")}

to_analyze = []
for (pid, data) in db.execute("SELECT id, data FROM raw_posts WHERE id LIKE 'reddit_%'"):
    if pid in existing_analyses:
        continue
    d = json.loads(data)
    if d.get("is_trusted"):
        to_analyze.append(d)

log.info("loaded", count=len(to_analyze))

if not to_analyze:
    print("Nothing to analyze.")
    sys.exit(0)

batch = cfg.llm.batch_size
analyses = []
for i in range(0, len(to_analyze), batch):
    chunk = to_analyze[i:i + batch]
    results = analyzer.analyze_batch(chunk)
    analyses.extend(results)
    print(f"  analyzed {len(analyses)}/{len(to_analyze)}")

storage.upsert_batch("analyses", analyses)
log.info("analyses_stored", count=len(analyses))

# Aggregate + alerts
agg = Aggregator(storage)
result = agg.aggregate_window("daily")
log.info("aggregate", **{"window": result.get("time_window", "none")})

engine = AlertEngine(storage)
alerts = engine.detect_all()
for a in alerts:
    storage.upsert("alerts", a)
log.info("alerts_generated", count=len(alerts))

print(f"\nDone. analyzed={len(analyses)} alerts={len(alerts)}")
