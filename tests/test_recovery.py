"""Tests for recovery from crashes and restarts."""

from __future__ import annotations

from pathlib import Path

import pytest

from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus, MediaType
from photoport.storage.repository import MediaItemRepository


@pytest.fixture
def db_path(tmp_path: Path):
    return tmp_path / "recovery_test.db"


def _populate_db(db: Database) -> None:
    """Populate the database with items in various states to simulate a crash."""
    repo = MediaItemRepository(db)

    # Some completed items
    for i in range(5):
        item = MediaItem(
            archive_path="archive.zip",
            zip_member_path=f"uploaded_{i}.jpg",
            file_name=f"uploaded_{i}.jpg",
            file_size=1000,
            media_type=MediaType.PHOTO,
            mime_type="image/jpeg",
            status=MediaItemStatus.UPLOADED,
            google_media_id=f"g_id_{i}",
        )
        repo.insert(item)

    # Some pending items
    for i in range(3):
        item = MediaItem(
            archive_path="archive.zip",
            zip_member_path=f"pending_{i}.jpg",
            file_name=f"pending_{i}.jpg",
            file_size=2000,
            media_type=MediaType.PHOTO,
            mime_type="image/jpeg",
            status=MediaItemStatus.READY,
        )
        repo.insert(item)

    # One item left in UPLOADING state (crash during upload)
    item = MediaItem(
        archive_path="archive.zip",
        zip_member_path="interrupted.jpg",
        file_name="interrupted.jpg",
        file_size=5000,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=MediaItemStatus.UPLOADING,
    )
    repo.insert(item)

    # Some failed items
    for i in range(2):
        item = MediaItem(
            archive_path="archive.zip",
            zip_member_path=f"failed_{i}.jpg",
            file_name=f"failed_{i}.jpg",
            file_size=3000,
            media_type=MediaType.PHOTO,
            mime_type="image/jpeg",
            status=MediaItemStatus.FAILED_RETRYABLE,
            error_message="Connection timeout",
            retry_count=1,
        )
        repo.insert(item)


class TestRecoveryAfterCrash:
    """Test that migration can resume after application crash."""

    def test_database_persists_across_connections(self, db_path: Path):
        """Verify data survives database close and reopen."""
        # First connection: populate
        db1 = Database(db_path)
        _populate_db(db1)
        repo1 = MediaItemRepository(db1)
        assert repo1.total_count() == 11
        db1.close()

        # Second connection: verify
        db2 = Database(db_path)
        repo2 = MediaItemRepository(db2)
        assert repo2.total_count() == 11
        db2.close()

    def test_recover_interrupted_uploads(self, db_path: Path):
        """Items left in UPLOADING state after crash should be recoverable."""
        db = Database(db_path)
        _populate_db(db)
        repo = MediaItemRepository(db)

        # Find items in UPLOADING state (interrupted by crash)
        uploading = repo.get_by_status(MediaItemStatus.UPLOADING)
        assert len(uploading) == 1
        assert uploading[0].file_name == "interrupted.jpg"

        # Recovery: reset to READY (since we can't confirm upload completed)
        for item in uploading:
            repo.update_status(
                item.id,
                MediaItemStatus.READY,
                error_message="Reset after application crash — upload status unknown",
            )

        # Verify recovery
        ready = repo.get_by_status(MediaItemStatus.READY)
        assert any(i.file_name == "interrupted.jpg" for i in ready)
        db.close()

    def test_completed_uploads_preserved(self, db_path: Path):
        """Already-uploaded items should not be re-uploaded after restart."""
        db = Database(db_path)
        _populate_db(db)
        repo = MediaItemRepository(db)

        uploaded = repo.get_by_status(MediaItemStatus.UPLOADED)
        assert len(uploaded) == 5
        assert all(i.google_media_id.startswith("g_id_") for i in uploaded)
        db.close()

    def test_pending_items_still_pending(self, db_path: Path):
        """Pending items should remain in queue after restart."""
        db = Database(db_path)
        _populate_db(db)
        repo = MediaItemRepository(db)

        ready = repo.get_by_status(MediaItemStatus.READY)
        assert len(ready) == 3
        db.close()

    def test_retryable_failures_available(self, db_path: Path):
        """Failed-retryable items should be available for retry."""
        db = Database(db_path)
        _populate_db(db)
        repo = MediaItemRepository(db)

        retryable = repo.get_retryable(max_retries=5)
        assert len(retryable) == 2
        db.close()

    def test_status_counts_after_recovery(self, db_path: Path):
        """Verify accurate counts after simulated crash recovery."""
        db = Database(db_path)
        _populate_db(db)
        repo = MediaItemRepository(db)

        counts = repo.count_by_status()
        assert counts.get("UPLOADED", 0) == 5
        assert counts.get("READY", 0) == 3
        assert counts.get("UPLOADING", 0) == 1
        assert counts.get("FAILED_RETRYABLE", 0) == 2
        db.close()

    def test_migration_manager_distinguishes_crash_states(self, db_path: Path, tmp_path: Path):
        """Test that MigrationManager cleanly distinguishes crash states:
        - No upload token: reset to READY
        - Upload token present (ambiguous batchCreate): marked as NEEDS_REVIEW
        - Google media ID present: marked as UPLOADED
        """
        from photoport.config import AppConfig
        from photoport.migration.migration_manager import MigrationManager

        db = Database(db_path)
        repo = MediaItemRepository(db)

        # 1. Interrupted during byte stream (no token)
        item1 = MediaItem(
            archive_path="a.zip", zip_member_path="no_token.jpg", file_name="no_token.jpg",
            status=MediaItemStatus.UPLOADING, upload_token="",
        )
        id1 = repo.insert(item1)

        # 2. Interrupted after byte upload (has token, batchCreate in flight)
        item2 = MediaItem(
            archive_path="a.zip", zip_member_path="with_token.jpg", file_name="with_token.jpg",
            status=MediaItemStatus.UPLOADING, upload_token="tok_123_abc",
        )
        id2 = repo.insert(item2)

        # 3. Interrupted after confirmed creation
        item3 = MediaItem(
            archive_path="a.zip", zip_member_path="has_id.jpg", file_name="has_id.jpg",
            status=MediaItemStatus.UPLOADING, google_media_id="g_id_999",
        )
        id3 = repo.insert(item3)

        config = AppConfig(temp_dir=tmp_path)
        manager = MigrationManager(config=config, db=db)

        results = manager.recover_interrupted_uploads()
        assert results["reset_ready"] == 1
        assert results["marked_review"] == 1
        assert results["marked_uploaded"] == 1

        # Check states in database
        res1 = repo.get_by_id(id1)
        assert res1.status == MediaItemStatus.READY

        res2 = repo.get_by_id(id2)
        assert res2.status == MediaItemStatus.NEEDS_REVIEW
        assert res2.upload_token == "tok_123_abc"

        res3 = repo.get_by_id(id3)
        assert res3.status == MediaItemStatus.UPLOADED
        assert res3.google_media_id == "g_id_999"

        # Test reconciliation of item2
        assert manager.reconcile_item(id2, "mark_uploaded", note="Confirmed in Google Photos")
        res2_after = repo.get_by_id(id2)
        assert res2_after.status == MediaItemStatus.UPLOADED

        # Test force retry reconciliation
        item4 = MediaItem(
            archive_path="a.zip", zip_member_path="retry_me.jpg", file_name="retry_me.jpg",
            status=MediaItemStatus.NEEDS_REVIEW, upload_token="old_tok",
        )
        id4 = repo.insert(item4)
        assert manager.reconcile_item(id4, "force_retry")
        res4 = repo.get_by_id(id4)
        assert res4.status == MediaItemStatus.READY
        assert res4.upload_token == ""  # token reset for fresh upload

        # Test skip reconciliation
        item5 = MediaItem(
            archive_path="a.zip", zip_member_path="skip_me.jpg", file_name="skip_me.jpg",
            status=MediaItemStatus.NEEDS_REVIEW,
        )
        id5 = repo.insert(item5)
        assert manager.reconcile_item(id5, "skip")
        res5 = repo.get_by_id(id5)
        assert res5.status == MediaItemStatus.SKIPPED

        db.close()
