"""Run aggregate + alert detection on whatever is currently in storage."""
import sys
sys.path.insert(0, ".")

from src.utils.config import load_config
from src.utils.logger import setup_logging, get_logger
from src.storage.store import create_storage
from src.aggregation.aggregator import Aggregator
from src.alerts.engine import AlertEngine

setup_logging()
log = get_logger("aggregate_only")

cfg = load_config()
storage = create_storage(cfg.storage)

agg = Aggregator(storage)
result = agg.aggregate_window("daily")
log.info("aggregate_daily", window=result.get("time_window", "none"))

result_h = agg.aggregate_window("hourly")
log.info("aggregate_hourly", window=result_h.get("time_window", "none"))

engine = AlertEngine(storage)
alerts = engine.detect_all()
for a in alerts:
    storage.upsert("alerts", a)
log.info("alerts_generated", count=len(alerts))

print(f"\nDone. alerts={len(alerts)}")
