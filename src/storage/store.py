"""
Retail Sentiment Intelligence — Storage Abstraction
Supports SQLite (local dev) and Cosmos DB (production).
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
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

            CREATE TABLE IF NOT EXISTS post_lifecycle (
                post_id TEXT PRIMARY KEY,
                subreddit TEXT,
                state TEXT NOT NULL,           -- new | acknowledged | reply_sent | issue_fixed | resolved
                priority TEXT,                 -- low | medium | high
                title TEXT,
                top_aspect TEXT,
                sentiment_score REAL,
                sentiment_confidence REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                acknowledged_at TEXT,
                reply_sent_at TEXT,
                resolved_at TEXT,
                reddit_posted_id TEXT,
                history_json TEXT,             -- JSON list of {at, from_state, to_state, by, note}
                data TEXT                      -- JSON blob with the rest
            );
            CREATE INDEX IF NOT EXISTS idx_lifecycle_state ON post_lifecycle(state);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_created ON post_lifecycle(created_at DESC);

            CREATE TABLE IF NOT EXISTS insights (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,            -- 'competitor_daily' | 'competitor_on_demand'
                window_days INTEGER,
                generated_at TEXT NOT NULL,
                payload TEXT                   -- JSON blob
            );
            CREATE INDEX IF NOT EXISTS idx_insights_kind_gen ON insights(kind, generated_at DESC);

            -- Notification groups: which subreddit groups get notified and how
            CREATE TABLE IF NOT EXISTS notification_groups (
                id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL,
                subreddits TEXT NOT NULL,       -- JSON array of subreddit names
                email_dl TEXT NOT NULL DEFAULT '[]', -- JSON array of email DLs
                slack_channel TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority_filter TEXT NOT NULL DEFAULT '["P1","P2"]', -- JSON array
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Notification log: track every notification sent
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                channel TEXT NOT NULL,          -- 'email' | 'slack'
                status TEXT NOT NULL,           -- 'sent' | 'failed' | 'dry_run'
                error TEXT,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES notification_groups(id)
            );
            CREATE INDEX IF NOT EXISTS idx_notiflog_post ON notification_log(post_id);
            CREATE INDEX IF NOT EXISTS idx_notiflog_group ON notification_log(group_id);
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

    def flush_all(self) -> dict[str, int]:
        """Delete all rows from data tables (raw_posts, analyses, aggregates, feedback, alerts, pipeline_runs).

        Cursors are NOT deleted here — call CursorTracker.reset_all() separately.
        Caller is responsible for backing up the DB file before invoking.
        Returns row counts deleted per table.
        """
        tables = ["raw_posts", "analyses", "aggregates", "feedback", "alerts", "pipeline_runs"]
        deleted: dict[str, int] = {}
        for tbl in tables:
            try:
                cur = self._conn.execute(f"SELECT COUNT(*) FROM {tbl}")
                deleted[tbl] = cur.fetchone()[0]
                self._conn.execute(f"DELETE FROM {tbl}")
            except sqlite3.OperationalError:
                deleted[tbl] = 0
        self._conn.commit()
        # Reclaim disk
        try:
            self._conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
        log.warning("flush_all", deleted=deleted)
        return deleted

    # ─── Post Lifecycle (Phase 4) ───────────────────────────────────────
    LIFECYCLE_STATES = ("new", "acknowledged", "reply_sent", "issue_fixed", "resolved")

    def lifecycle_upsert(self, row: dict) -> None:
        """Insert or update a lifecycle row. `row` is a dict; arbitrary extra
        keys land in the `data` JSON blob.
        """
        history = row.get("history") or []
        cols = {
            "post_id": row["post_id"],
            "subreddit": row.get("subreddit", ""),
            "state": row.get("state", "new"),
            "priority": row.get("priority", "medium"),
            "title": (row.get("title") or "")[:500],
            "top_aspect": row.get("top_aspect", ""),
            "sentiment_score": float(row.get("sentiment_score") or 0.0),
            "sentiment_confidence": float(row.get("sentiment_confidence") or 0.0),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "acknowledged_at": row.get("acknowledged_at"),
            "reply_sent_at": row.get("reply_sent_at"),
            "resolved_at": row.get("resolved_at"),
            "reddit_posted_id": row.get("reddit_posted_id"),
            "history_json": json.dumps(history),
            "data": json.dumps(row),
        }
        self._conn.execute(
            """INSERT OR REPLACE INTO post_lifecycle
               (post_id, subreddit, state, priority, title, top_aspect,
                sentiment_score, sentiment_confidence, created_at, updated_at,
                acknowledged_at, reply_sent_at, resolved_at, reddit_posted_id,
                history_json, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(cols.values()),
        )
        self._conn.commit()

    def lifecycle_get(self, post_id: str) -> Optional[dict]:
        cur = self._conn.execute("SELECT data FROM post_lifecycle WHERE post_id = ?", (post_id,))
        row = cur.fetchone()
        return json.loads(row["data"]) if row else None

    def lifecycle_list(self, state: Optional[str] = None, limit: int = 200) -> list[dict]:
        if state:
            cur = self._conn.execute(
                "SELECT data FROM post_lifecycle WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                (state, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT data FROM post_lifecycle ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [json.loads(r["data"]) for r in cur.fetchall()]

    def lifecycle_counts(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM post_lifecycle GROUP BY state"
        )
        return {row["state"]: row["n"] for row in cur.fetchall()}

    # ─── Competitor insights (Phase 5) ──────────────────────────────────
    def insights_upsert(self, kind: str, window_days: int, payload: dict, generated_at: str) -> str:
        item_id = f"{kind}_{window_days}d_{generated_at}"
        self._conn.execute(
            "INSERT OR REPLACE INTO insights (id, kind, window_days, generated_at, payload) VALUES (?,?,?,?,?)",
            (item_id, kind, window_days, generated_at, json.dumps(payload)),
        )
        self._conn.commit()
        return item_id

    def insights_latest(self, kind: str = "competitor_daily") -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT id, kind, window_days, generated_at, payload FROM insights WHERE kind = ? ORDER BY generated_at DESC LIMIT 1",
            (kind,),
        )
        row = cur.fetchone()
        if not row:
            return None
        out = dict(row)
        out["payload"] = json.loads(row["payload"])
        return out

    def insights_history(self, limit: int = 20) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, kind, window_days, generated_at FROM insights ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ─── Notification Groups ────────────────────────────────────────────
    def notification_groups_list(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM notification_groups ORDER BY group_name"
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["subreddits"] = json.loads(r["subreddits"])
            r["email_dl"] = json.loads(r["email_dl"])
            r["priority_filter"] = json.loads(r["priority_filter"])
            r["enabled"] = bool(r["enabled"])
        return rows

    def notification_group_get(self, group_id: str) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM notification_groups WHERE id = ?", (group_id,))
        row = cur.fetchone()
        if not row:
            return None
        r = dict(row)
        r["subreddits"] = json.loads(r["subreddits"])
        r["email_dl"] = json.loads(r["email_dl"])
        r["priority_filter"] = json.loads(r["priority_filter"])
        r["enabled"] = bool(r["enabled"])
        return r

    def notification_group_upsert(self, group: dict) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            """INSERT OR REPLACE INTO notification_groups
               (id, group_name, subreddits, email_dl, slack_channel, enabled, priority_filter, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM notification_groups WHERE id = ?), ?), ?)""",
            (
                group["id"], group["group_name"],
                json.dumps(group.get("subreddits", [])),
                json.dumps(group.get("email_dl", [])),
                group.get("slack_channel", ""),
                1 if group.get("enabled", True) else 0,
                json.dumps(group.get("priority_filter", ["P1", "P2"])),
                group["id"], now, now,
            ),
        )
        self._conn.commit()

    def notification_group_delete(self, group_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM notification_groups WHERE id = ?", (group_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def notification_log_insert(self, group_id: str, post_id: str, channel: str, status: str, error: str | None = None) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            "INSERT INTO notification_log (group_id, post_id, channel, status, error, sent_at) VALUES (?,?,?,?,?,?)",
            (group_id, post_id, channel, status, error, now),
        )
        self._conn.commit()

    def notification_log_for_post(self, post_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM notification_log WHERE post_id = ? ORDER BY sent_at DESC", (post_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    def notification_log_recent(self, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            """SELECT nl.*, ng.group_name FROM notification_log nl
               LEFT JOIN notification_groups ng ON nl.group_id = ng.id
               ORDER BY nl.sent_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    def notification_groups_for_subreddit(self, subreddit: str) -> list[dict]:
        """Find all enabled notification groups that include this subreddit."""
        groups = self.notification_groups_list()
        return [g for g in groups if g["enabled"] and subreddit in g["subreddits"]]

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
