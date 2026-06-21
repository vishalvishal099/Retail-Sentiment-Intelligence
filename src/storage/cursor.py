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
        # Per-run, per-subreddit audit trail of the fetch window we actually
        # asked the upstream API for. Lets analysts spot gaps, replay missed
        # windows, and confirm the overlap buffer is working.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cursor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                subreddit TEXT,
                provider TEXT,
                cursor_before REAL,
                since_utc REAL,
                until_utc REAL,
                overlap_seconds INTEGER,
                fetched INTEGER,
                status TEXT,
                error TEXT,
                recorded_at TEXT
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cursor_history_subreddit_time "
            "ON cursor_history(subreddit, recorded_at DESC)"
        )
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

    def list_cursors(self) -> list[dict]:
        """Return every cursor row plus the most-recent history entry per
        subreddit. Used by the dashboard's /api/pipeline/cursors endpoint."""
        rows = self._conn.execute(
            "SELECT subreddit, last_fetched_utc, last_fetched_id, updated_at "
            "FROM cursors ORDER BY subreddit"
        ).fetchall()
        out: list[dict] = []
        for sub, last_utc, last_id, updated_at in rows:
            hist = self._conn.execute(
                "SELECT since_utc, until_utc, fetched, status, recorded_at, overlap_seconds "
                "FROM cursor_history WHERE subreddit = ? "
                "ORDER BY recorded_at DESC LIMIT 1",
                (sub,),
            ).fetchone()
            out.append({
                "subreddit": sub,
                "last_fetched_utc": last_utc,
                "last_fetched_id": last_id,
                "updated_at": updated_at,
                "last_window": {
                    "since_utc": hist[0],
                    "until_utc": hist[1],
                    "fetched": hist[2],
                    "status": hist[3],
                    "recorded_at": hist[4],
                    "overlap_seconds": hist[5],
                } if hist else None,
            })
        return out

    def record_history(
        self,
        run_id: str,
        subreddit: str,
        provider: str,
        cursor_before: float,
        since_utc: float,
        until_utc: float,
        overlap_seconds: int,
        fetched: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Append one row to the cursor_history audit log."""
        self._conn.execute(
            """INSERT INTO cursor_history
               (run_id, subreddit, provider, cursor_before, since_utc, until_utc,
                overlap_seconds, fetched, status, error, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, subreddit, provider, cursor_before, since_utc, until_utc,
             overlap_seconds, fetched, status, error,
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def reset_all(self) -> int:
        """Delete every cursor row so the next ingestion fetches from scratch.

        Returns the number of cursor rows that were removed.
        """
        cur = self._conn.execute("SELECT COUNT(*) FROM cursors")
        deleted = cur.fetchone()[0]
        self._conn.execute("DELETE FROM cursors")
        self._conn.commit()
        log.warning("cursors_reset", deleted=deleted)
        return deleted

    def close(self):
        self._conn.close()
