"""
Retail Sentiment Intelligence — Storage Abstraction
Supports SQLite (local dev) and Cosmos DB (production).
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.utils.config import StorageConfig
from src.utils.logger import get_logger

log = get_logger("storage")


class StorageBackend(ABC):
    """Abstract storage backend."""

    @abstractmethod
    def upsert(self, container: str, item: dict) -> None:
        ...

    @abstractmethod
    def upsert_batch(self, container: str, items: list[dict]) -> int:
        ...

    @abstractmethod
    def query(self, container: str, query_str: str, parameters: Optional[list] = None) -> list[dict]:
        ...

    @abstractmethod
    def get_item(self, container: str, item_id: str, partition_key: str) -> Optional[dict]:
        ...


class SQLiteBackend(StorageBackend):
    """SQLite storage for local development."""

    def __init__(self, db_path: str = "data/local.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """Create tables matching Cosmos container structure."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_posts (
                id TEXT PRIMARY KEY,
                subreddit TEXT,
                data JSON NOT NULL,
                created_timestamp REAL,
                processing_status TEXT DEFAULT 'pending'
            );
            CREATE INDEX IF NOT EXISTS idx_raw_posts_subreddit ON raw_posts(subreddit);
            CREATE INDEX IF NOT EXISTS idx_raw_posts_status ON raw_posts(processing_status);
            CREATE INDEX IF NOT EXISTS idx_raw_posts_created ON raw_posts(created_timestamp);

            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                post_id TEXT,
                subreddit TEXT,
                data JSON NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_post ON analyses(post_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_subreddit ON analyses(subreddit);

            CREATE TABLE IF NOT EXISTS aggregates (
                id TEXT PRIMARY KEY,
                time_window TEXT,
                window_type TEXT,
                data JSON NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_aggregates_window ON aggregates(time_window);

            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                analyst_id TEXT,
                post_id TEXT,
                data JSON NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                type TEXT,
                severity TEXT,
                time_window TEXT,
                data JSON NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(type);
            CREATE INDEX IF NOT EXISTS idx_alerts_window ON alerts(time_window);

            CREATE TABLE IF NOT EXISTS cursors (
                subreddit TEXT PRIMARY KEY,
                last_fetched_utc REAL,
                last_fetched_id TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT,           -- running | success | failed
                trigger TEXT,          -- manual | scheduled | backfill
                duration_ms INTEGER,
                counters_json TEXT,    -- JSON: {ingested, processed, trusted, flagged, analyzed, ...}
                params_json TEXT,      -- JSON: {from, to, subreddits} for backfills
                error TEXT,
                log_tail TEXT          -- last ~25 lines of subprocess output
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
        """)
        self._conn.commit()

    def upsert(self, container: str, item: dict) -> None:
        item_id = item.get("id", "")
        data_json = json.dumps(item)

        if container == "raw_posts":
            self._conn.execute(
                "INSERT OR REPLACE INTO raw_posts (id, subreddit, data, created_timestamp, processing_status) VALUES (?, ?, ?, ?, ?)",
                (item_id, item.get("subreddit", ""), data_json,
                 item.get("created_timestamp", 0), item.get("processing_status", "pending"))
            )
        elif container == "analyses":
            self._conn.execute(
                "INSERT OR REPLACE INTO analyses (id, post_id, subreddit, data) VALUES (?, ?, ?, ?)",
                (item_id, item.get("post_id", ""), item.get("subreddit", ""), data_json)
            )
        elif container == "aggregates":
            self._conn.execute(
                "INSERT OR REPLACE INTO aggregates (id, time_window, window_type, data) VALUES (?, ?, ?, ?)",
                (item_id, item.get("time_window", ""), item.get("window_type", ""), data_json)
            )
        elif container == "feedback":
            self._conn.execute(
                "INSERT OR REPLACE INTO feedback (id, analyst_id, post_id, data) VALUES (?, ?, ?, ?)",
                (item_id, item.get("analyst_id", ""), item.get("post_id", ""), data_json)
            )
        elif container == "alerts":
            self._conn.execute(
                "INSERT OR REPLACE INTO alerts (id, type, severity, time_window, data) VALUES (?, ?, ?, ?, ?)",
                (item_id, item.get("type", ""), item.get("severity", ""), item.get("time_window", ""), data_json)
            )
        self._conn.commit()

    def upsert_batch(self, container: str, items: list[dict]) -> int:
        count = 0
        for item in items:
            self.upsert(container, item)
            count += 1
        return count

    def query(self, container: str, query_str: str, parameters: Optional[list] = None) -> list[dict]:
        """Execute a query. For SQLite, query_str is SQL WHERE clause or full SQL."""
        try:
            cursor = self._conn.execute(query_str, parameters or [])
            rows = cursor.fetchall()
            return [json.loads(row["data"]) for row in rows]
        except Exception as e:
            log.error("query_failed", container=container, error=str(e))
            return []

    def get_item(self, container: str, item_id: str, partition_key: str = "") -> Optional[dict]:
        try:
            cursor = self._conn.execute(
                f"SELECT data FROM {container} WHERE id = ?", (item_id,)
            )
            row = cursor.fetchone()
            return json.loads(row["data"]) if row else None
        except Exception:
            return None

    def get_pending_posts(self, limit: int = 50) -> list[dict]:
        """Get posts/comments pending analysis."""
        cursor = self._conn.execute(
            "SELECT data FROM raw_posts WHERE processing_status = 'pending' ORDER BY created_timestamp ASC LIMIT ?",
            (limit,)
        )
        return [json.loads(row["data"]) for row in cursor.fetchall()]

    def update_status(self, item_id: str, status: str):
        """Update processing status of a raw post."""
        self._conn.execute(
            "UPDATE raw_posts SET processing_status = ? WHERE id = ?",
            (status, item_id)
        )
        self._conn.commit()

    def close(self):
        self._conn.close()


class CosmosBackend(StorageBackend):
    """Azure Cosmos DB storage backend."""

    def __init__(self, config: StorageConfig):
        from azure.cosmos import CosmosClient
        self.client = CosmosClient(config.cosmos_endpoint, config.cosmos_key)
        self.database = self.client.get_database_client(config.cosmos_database)
        self._containers = {}

    def _get_container(self, name: str):
        if name not in self._containers:
            self._containers[name] = self.database.get_container_client(name)
        return self._containers[name]

    def upsert(self, container: str, item: dict) -> None:
        self._get_container(container).upsert_item(item)

    def upsert_batch(self, container: str, items: list[dict]) -> int:
        container_client = self._get_container(container)
        count = 0
        for item in items:
            container_client.upsert_item(item)
            count += 1
        return count

    def query(self, container: str, query_str: str, parameters: Optional[list] = None) -> list[dict]:
        container_client = self._get_container(container)
        return list(container_client.query_items(
            query=query_str,
            parameters=parameters or [],
            enable_cross_partition_query=True,
        ))

    def get_item(self, container: str, item_id: str, partition_key: str = "") -> Optional[dict]:
        try:
            return self._get_container(container).read_item(item=item_id, partition_key=partition_key)
        except Exception:
            return None


def create_storage(config: StorageConfig) -> StorageBackend:
    """Factory: create the appropriate storage backend."""
    if config.provider == "cosmos" and config.cosmos_endpoint and config.cosmos_key:
        log.info("storage_init", provider="cosmos")
        return CosmosBackend(config)
    else:
        log.info("storage_init", provider="sqlite", path=config.sqlite_path)
        return SQLiteBackend(config.sqlite_path)
