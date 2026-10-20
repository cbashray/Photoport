"""Tests for migration state management."""

from __future__ import annotations

from pathlib import Path

import pytest

from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus, MediaType, MigrationSession
from photoport.storage.repository import MediaItemRepository, SessionRepository


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def repo(db: Database):
    return MediaItemRepository(db)


@pytest.fixture
def session_repo(db: Database):
    return SessionRepository(db)


def _make_item(member: str = "photo.jpg", status: MediaItemStatus = MediaItemStatus.DISCOVERED):
    return MediaItem(
        archive_path="test.zip",
        zip_member_path=member,
        file_name=member,
        file_size=1000,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=status,
    )


class TestStatusTransitions:
    """Test media item status lifecycle."""

    def test_discover_to_ready(self, repo: MediaItemRepository):
        item = _make_item()
        item_id = repo.insert(item)
        assert item_id > 0

        repo.update_status(item_id, MediaItemStatus.READY)
        updated = repo.get_by_id(item_id)
        assert updated is not None
        assert updated.status == MediaItemStatus.READY

    def test_ready_to_uploading_to_uploaded(self, repo: MediaItemRepository):
        item_id = repo.insert(_make_item())

        repo.update_status(item_id, MediaItemStatus.READY)
        repo.update_status(item_id, MediaItemStatus.UPLOADING)
        repo.update_status(
            item_id, MediaItemStatus.UPLOADED,
            google_media_id="google_123",
        )

        uploaded = repo.get_by_id(item_id)
        assert uploaded is not None
        assert uploaded.status == MediaItemStatus.UPLOADED
        assert uploaded.google_media_id == "google_123"

    def test_failed_retryable_transition(self, repo: MediaItemRepository):
        item_id = repo.insert(_make_item())

        repo.update_status(
            item_id, MediaItemStatus.FAILED_RETRYABLE,
            error_message="Connection timeout",
        )
        repo.increment_retry(item_id)

        item = repo.get_by_id(item_id)
        assert item is not None
        assert item.status == MediaItemStatus.FAILED_RETRYABLE
        assert item.retry_count == 1
        assert item.error_message == "Connection timeout"

    def test_get_retryable_items(self, repo: MediaItemRepository):
        for i in range(3):
            item_id = repo.insert(_make_item(member=f"photo{i}.jpg"))
            repo.update_status(
                item_id, MediaItemStatus.FAILED_RETRYABLE,
                error_message="timeout",
            )

        retryable = repo.get_retryable(max_retries=5, limit=10)
        assert len(retryable) == 3

    def test_exhausted_retries_excluded(self, repo: MediaItemRepository):
        item_id = repo.insert(_make_item())
        repo.update_status(item_id, MediaItemStatus.FAILED_RETRYABLE)
        # Simulate 5 retries
        for _ in range(5):
            repo.increment_retry(item_id)

        retryable = repo.get_retryable(max_retries=5, limit=10)
        assert len(retryable) == 0


class TestStatusCounts:
    """Test count-by-status queries."""

    def test_count_by_status(self, repo: MediaItemRepository):
        for i in range(5):
            repo.insert(_make_item(member=f"discovered{i}.jpg"))
        for i in range(3):
            item_id = repo.insert(_make_item(member=f"uploaded{i}.jpg"))
            repo.update_status(item_id, MediaItemStatus.UPLOADED)
        for i in range(2):
            item_id = repo.insert(_make_item(member=f"failed{i}.jpg"))
            repo.update_status(item_id, MediaItemStatus.FAILED_PERMANENT)

        counts = repo.count_by_status()
        assert counts.get("DISCOVERED", 0) == 5
        assert counts.get("UPLOADED", 0) == 3
        assert counts.get("FAILED_PERMANENT", 0) == 2

    def test_total_count(self, repo: MediaItemRepository):
        for i in range(7):
            repo.insert(_make_item(member=f"item{i}.jpg"))
        assert repo.total_count() == 7


class TestSessionPersistence:
    """Test migration session recording."""

    def test_create_and_retrieve_session(self, session_repo: SessionRepository):
        session = MigrationSession(
            total_archives=3,
            destination_account="user@gmail.com",
        )
        session_id = session_repo.create(session)
        assert session_id > 0

        latest = session_repo.get_latest()
        assert latest is not None
        assert latest.total_archives == 3
        assert latest.status == "IN_PROGRESS"

    def test_update_session(self, session_repo: SessionRepository):
        session = MigrationSession(total_archives=1)
        session.id = session_repo.create(session)
        session.total_uploaded = 50
        session.status = "COMPLETED"
        session.completed_at = "2024-01-01T00:00:00"

        session_repo.update(session)

        latest = session_repo.get_latest()
        assert latest is not None
        assert latest.total_uploaded == 50
        assert latest.status == "COMPLETED"
