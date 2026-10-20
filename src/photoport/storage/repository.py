"""Repository layer — CRUD operations for the migration ledger."""

from __future__ import annotations

import logging
from datetime import datetime

from photoport.storage.database import Database
from photoport.storage.models import (
    AlbumRecord,
    MediaItem,
    MediaItemStatus,
    MediaType,
    MigrationSession,
)

logger = logging.getLogger("photoport.storage.repository")


class MediaItemRepository:
    """Data-access methods for media items."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, item: MediaItem) -> int:
        """Insert a new media item and return its ID."""
        now = datetime.utcnow().isoformat()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO media_items
                   (archive_path, zip_member_path, file_name, file_size, media_type,
                    sha256_hash, mime_type, status, upload_token, google_media_id,
                    album_name, description, capture_timestamp, error_message,
                    retry_count, last_attempt, sidecar_path, latitude, longitude,
                    exif_injected, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.archive_path, item.zip_member_path, item.file_name,
                    item.file_size, item.media_type.value, item.sha256_hash,
                    item.mime_type, item.status.value, item.upload_token, item.google_media_id,
                    item.album_name, item.description, item.capture_timestamp, item.error_message,
                    item.retry_count, item.last_attempt, item.sidecar_path,
                    item.latitude, item.longitude, int(item.exif_injected),
                    now, now,
                ),
            )
            return cursor.lastrowid or 0

    def insert_batch(self, items: list[MediaItem]) -> int:
        """Insert multiple media items. Returns count inserted."""
        now = datetime.utcnow().isoformat()
        count = 0
        with self.db.transaction() as conn:
            for item in items:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO media_items
                       (archive_path, zip_member_path, file_name, file_size, media_type,
                        sha256_hash, mime_type, status, upload_token, google_media_id,
                        album_name, description, capture_timestamp, error_message,
                        retry_count, last_attempt, sidecar_path, latitude, longitude,
                        exif_injected, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.archive_path, item.zip_member_path, item.file_name,
                        item.file_size, item.media_type.value, item.sha256_hash,
                        item.mime_type, item.status.value, item.upload_token, item.google_media_id,
                        item.album_name, item.description, item.capture_timestamp, item.error_message,
                        item.retry_count, item.last_attempt, item.sidecar_path,
                        item.latitude, item.longitude, int(item.exif_injected),
                        now, now,
                    ),
                )
                if cursor.rowcount > 0:
                    count += 1
        return count

    def update_status(
        self,
        item_id: int,
        status: MediaItemStatus,
        error_message: str = "",
        google_media_id: str = "",
        upload_token: str = "",
    ) -> None:
        """Update item status and related fields."""
        now = datetime.utcnow().isoformat()
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE media_items
                   SET status = ?, error_message = ?, google_media_id = ?,
                       upload_token = ?, last_attempt = ?, updated_at = ?
                   WHERE id = ?""",
                (status.value, error_message, google_media_id, upload_token, now, now, item_id),
            )

    def increment_retry(self, item_id: int) -> None:
        """Increment retry count for an item."""
        now = datetime.utcnow().isoformat()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE media_items SET retry_count = retry_count + 1, last_attempt = ?, updated_at = ? WHERE id = ?",
                (now, now, item_id),
            )

    def update_hash(self, item_id: int, sha256_hash: str) -> None:
        """Update the SHA-256 hash for an item."""
        now = datetime.utcnow().isoformat()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE media_items SET sha256_hash = ?, updated_at = ? WHERE id = ?",
                (sha256_hash, now, item_id),
            )

    def get_by_id(self, item_id: int) -> MediaItem | None:
        """Fetch a single media item by ID."""
        with self.db.transaction() as conn:
            cursor = conn.execute("SELECT * FROM media_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            return self._row_to_item(row) if row else None

    def get_by_status(self, status: MediaItemStatus, limit: int = 100) -> list[MediaItem]:
        """Fetch media items with the given status."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM media_items WHERE status = ? ORDER BY id LIMIT ?",
                (status.value, limit),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_by_hash(self, sha256_hash: str) -> list[MediaItem]:
        """Find items with the given hash (for duplicate detection)."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM media_items WHERE sha256_hash = ?", (sha256_hash,)
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_all(self) -> list[MediaItem]:
        """Return all media items."""
        with self.db.transaction() as conn:
            cursor = conn.execute("SELECT * FROM media_items ORDER BY id")
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def count_by_status(self) -> dict[str, int]:
        """Return counts grouped by status."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM media_items GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}

    def total_size_by_status(self, status: MediaItemStatus) -> int:
        """Return total file size for items with the given status."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) as total FROM media_items WHERE status = ?",
                (status.value,),
            )
            row = cursor.fetchone()
            return row["total"] if row else 0

    def total_count(self) -> int:
        """Return total number of media items."""
        with self.db.transaction() as conn:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM media_items")
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def total_media_size(self) -> int:
        """Return total size of all media items in bytes."""
        with self.db.transaction() as conn:
            cursor = conn.execute("SELECT COALESCE(SUM(file_size), 0) as total FROM media_items")
            row = cursor.fetchone()
            return row["total"] if row else 0

    def remaining_upload_size(self, max_retries: int = 5) -> int:
        """Return total bytes of items that still need to be uploaded for a new or resumed session.

        Includes DISCOVERED, READY, ambiguous crash states (UPLOADING, NEEDS_REVIEW),
        and retryable failures under the max retry threshold.
        Excludes UPLOADED, VERIFIED, SKIPPED, and permanent failures.
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """SELECT COALESCE(SUM(file_size), 0) as total FROM media_items
                   WHERE status IN ('DISCOVERED', 'READY', 'UPLOADING', 'NEEDS_REVIEW')
                      OR (status = 'FAILED_RETRYABLE' AND retry_count < ?)""",
                (max_retries,),
            )
            row = cursor.fetchone()
            return row["total"] if row else 0

    def remaining_item_count(self, max_retries: int = 5) -> int:
        """Return count of items that still need to be uploaded."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """SELECT COUNT(*) as cnt FROM media_items
                   WHERE status IN ('DISCOVERED', 'READY', 'UPLOADING', 'NEEDS_REVIEW')
                      OR (status = 'FAILED_RETRYABLE' AND retry_count < ?)""",
                (max_retries,),
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def uploaded_media_size(self) -> int:
        """Return total bytes of successfully uploaded or verified media items."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) as total FROM media_items WHERE status IN ('UPLOADED', 'VERIFIED')"
            )
            row = cursor.fetchone()
            return row["total"] if row else 0

    def ambiguous_media_size(self) -> int:
        """Return bytes of items in ambiguous states (in-flight crash or needs review)."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) as total FROM media_items WHERE status IN ('UPLOADING', 'NEEDS_REVIEW')"
            )
            row = cursor.fetchone()
            return row["total"] if row else 0

    def get_retryable(self, max_retries: int, limit: int = 50) -> list[MediaItem]:
        """Get items that failed but can be retried."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """SELECT * FROM media_items
                   WHERE status = ? AND retry_count < ?
                   ORDER BY last_attempt ASC LIMIT ?""",
                (MediaItemStatus.FAILED_RETRYABLE.value, max_retries, limit),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def exists(self, archive_path: str, zip_member_path: str) -> bool:
        """Check if an item already exists in the ledger."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM media_items WHERE archive_path = ? AND zip_member_path = ?",
                (archive_path, zip_member_path),
            )
            return cursor.fetchone() is not None

    @staticmethod
    def _row_to_item(row: dict) -> MediaItem:
        return MediaItem(
            id=row["id"],
            archive_path=row["archive_path"],
            zip_member_path=row["zip_member_path"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            media_type=MediaType(row["media_type"]),
            sha256_hash=row["sha256_hash"],
            mime_type=row["mime_type"],
            status=MediaItemStatus(row["status"]),
            upload_token=row["upload_token"],
            google_media_id=row["google_media_id"],
            album_name=row["album_name"],
            description=row["description"],
            capture_timestamp=row["capture_timestamp"],
            error_message=row["error_message"],
            retry_count=row["retry_count"],
            last_attempt=row["last_attempt"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sidecar_path=row["sidecar_path"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            exif_injected=bool(row["exif_injected"]),
        )


class AlbumRepository:
    """Data-access methods for albums."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, album: AlbumRecord) -> int:
        """Insert or update an album record. Returns the album ID."""
        now = datetime.utcnow().isoformat()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO albums (source_name, item_count, status, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_name) DO UPDATE SET
                   item_count = item_count + excluded.item_count""",
                (album.source_name, album.item_count, album.status, now),
            )
            return cursor.lastrowid or 0

    def update_google_id(self, source_name: str, google_album_id: str) -> None:
        """Record the Google Photos album ID after creation."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE albums SET google_album_id = ?, status = 'CREATED' WHERE source_name = ?",
                (google_album_id, source_name),
            )

    def increment_added(self, source_name: str) -> None:
        """Increment the count of items added to the album."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE albums SET items_added = items_added + 1 WHERE source_name = ?",
                (source_name,),
            )

    def get_all(self) -> list[AlbumRecord]:
        """Return all album records."""
        with self.db.transaction() as conn:
            cursor = conn.execute("SELECT * FROM albums ORDER BY source_name")
            return [self._row_to_album(row) for row in cursor.fetchall()]

    def get_by_name(self, source_name: str) -> AlbumRecord | None:
        """Fetch an album by source name."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM albums WHERE source_name = ?", (source_name,)
            )
            row = cursor.fetchone()
            return self._row_to_album(row) if row else None

    @staticmethod
    def _row_to_album(row: dict) -> AlbumRecord:
        return AlbumRecord(
            id=row["id"],
            source_name=row["source_name"],
            google_album_id=row["google_album_id"],
            item_count=row["item_count"],
            items_added=row["items_added"],
            status=row["status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )


class SessionRepository:
    """Data-access methods for migration sessions."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, session: MigrationSession) -> int:
        """Create a new migration session."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO migration_sessions
                   (started_at, total_archives, status, destination_account)
                   VALUES (?, ?, ?, ?)""",
                (session.started_at, session.total_archives, session.status,
                 session.destination_account),
            )
            return cursor.lastrowid or 0

    def update(self, session: MigrationSession) -> None:
        """Update session counters and status."""
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE migration_sessions SET
                   completed_at = ?, total_files_discovered = ?, total_photos = ?,
                   total_videos = ?, total_uploaded = ?, total_verified = ?,
                   total_failed = ?, total_skipped = ?, total_needs_review = ?,
                   status = ?
                   WHERE id = ?""",
                (
                    session.completed_at, session.total_files_discovered,
                    session.total_photos, session.total_videos,
                    session.total_uploaded, session.total_verified,
                    session.total_failed, session.total_skipped,
                    session.total_needs_review, session.status, session.id,
                ),
            )

    def get_latest(self) -> MigrationSession | None:
        """Fetch the most recent migration session."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM migration_sessions ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None
            return MigrationSession(
                id=row["id"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                total_archives=row["total_archives"],
                total_files_discovered=row["total_files_discovered"],
                total_photos=row["total_photos"],
                total_videos=row["total_videos"],
                total_uploaded=row["total_uploaded"],
                total_verified=row["total_verified"],
                total_failed=row["total_failed"],
                total_skipped=row["total_skipped"],
                total_needs_review=row["total_needs_review"],
                status=row["status"],
                destination_account=row["destination_account"],
            )
