"""
Retail Sentiment Intelligence — Cursor Tracking
Tracks last_fetched timestamp per subreddit for incremental ingestion.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

log = get_logger("cursor")


class CursorTracker:
    """Tracks ingestion cursors per subreddit in SQLite (works with both backends)."""

    def __init__(self, db_path: str = "data/local.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cursors (
                subreddit TEXT PRIMARY KEY,
                last_fetched_utc REAL,
                last_fetched_id TEXT,
                updated_at TEXT
            )
        """)
        self._conn.commit()

    def get_cursor(self, subreddit: str) -> float:
        """Get last fetched UTC timestamp for a subreddit. Returns 0 if never fetched."""
        cursor = self._conn.execute(
            "SELECT last_fetched_utc FROM cursors WHERE subreddit = ?",
            (subreddit,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0.0

    def update_cursor(self, subreddit: str, last_fetched_utc: float, last_fetched_id: str = ""):
        """Update cursor AFTER successful write."""
        self._conn.execute(
            "INSERT OR REPLACE INTO cursors (subreddit, last_fetched_utc, last_fetched_id, updated_at) VALUES (?, ?, ?, ?)",
            (subreddit, last_fetched_utc, last_fetched_id, datetime.now(timezone.utc).isoformat())
        )
        self._conn.commit()
        log.info("cursor_updated", subreddit=subreddit, last_utc=last_fetched_utc)

    def close(self):
        self._conn.close()
