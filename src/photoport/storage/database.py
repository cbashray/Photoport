"""SQLite database manager for the migration ledger."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("photoport.storage.database")

SCHEMA_VERSION = 1

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_path TEXT NOT NULL,
    zip_member_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    media_type TEXT NOT NULL DEFAULT 'UNKNOWN',
    sha256_hash TEXT DEFAULT '',
    mime_type TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    upload_token TEXT DEFAULT '',
    google_media_id TEXT DEFAULT '',
    album_name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    capture_timestamp TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sidecar_path TEXT DEFAULT '',
    latitude REAL,
    longitude REAL,
    exif_injected INTEGER NOT NULL DEFAULT 0,
    UNIQUE(archive_path, zip_member_path)
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL UNIQUE,
    google_album_id TEXT DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    items_added INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT '',
    total_archives INTEGER NOT NULL DEFAULT 0,
    total_files_discovered INTEGER NOT NULL DEFAULT 0,
    total_photos INTEGER NOT NULL DEFAULT 0,
    total_videos INTEGER NOT NULL DEFAULT 0,
    total_uploaded INTEGER NOT NULL DEFAULT 0,
    total_verified INTEGER NOT NULL DEFAULT 0,
    total_failed INTEGER NOT NULL DEFAULT 0,
    total_skipped INTEGER NOT NULL DEFAULT 0,
    total_needs_review INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    destination_account TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_media_status ON media_items(status);
CREATE INDEX IF NOT EXISTS idx_media_hash ON media_items(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_media_album ON media_items(album_name);
"""


class Database:
    """SQLite database connection manager with migration ledger operations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._initialize()

    def _initialize(self) -> None:
        """Create tables and apply schema migrations."""
        conn = self._get_connection()
        conn.executescript(CREATE_TABLES_SQL)
        # Record schema version
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        logger.info("Database initialized at %s (schema v%d)", self.db_path, SCHEMA_VERSION)

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=30)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that yields a connection inside a transaction."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
