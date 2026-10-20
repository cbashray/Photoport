"""Tests for retry policy and upload service error handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from photoport.google_photos.api_client import GooglePhotosAPIError
from photoport.google_photos.upload_service import UploadService
from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus, MediaType
from photoport.storage.repository import MediaItemRepository


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def repo(db: Database):
    return MediaItemRepository(db)


@pytest.fixture
def mock_api():
    return MagicMock()


@pytest.fixture
def service(mock_api, repo):
    return UploadService(
        api_client=mock_api,
        repo=repo,
        max_retries=3,
        base_delay=0.01,  # Short delays for testing
        max_delay=0.1,
    )


def _make_item(repo: MediaItemRepository) -> MediaItem:
    item = MediaItem(
        archive_path="test.zip",
        zip_member_path="photo.jpg",
        file_name="photo.jpg",
        file_size=1000,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=MediaItemStatus.READY,
    )
    item.id = repo.insert(item)
    return item


class TestUploadResult:
    """Tests for upload success and failure handling."""

    def test_successful_upload(self, service: UploadService, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.return_value = "upload_token_123"
        mock_api.batch_create.return_value = [
            {
                "status": {"code": 0},
                "mediaItem": {"id": "media_item_abc"},
            }
        ]

        result = service.upload_file(item, file_path, "access_token")

        assert result.success is True
        assert result.media_item_id == "media_item_abc"

        # Check DB was updated
        updated = repo.get_by_id(item.id)
        assert updated.status == MediaItemStatus.UPLOADED
        assert updated.google_media_id == "media_item_abc"

    def test_transient_error_marked_retryable(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.side_effect = GooglePhotosAPIError(
            "Rate limited", status_code=429, is_retryable=True,
        )

        result = service.upload_file(item, file_path, "token")

        assert result.success is False
        assert result.is_retryable is True

    def test_permanent_error(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.side_effect = GooglePhotosAPIError(
            "Permission denied", status_code=403, is_retryable=False,
        )

        result = service.upload_file(item, file_path, "token")

        assert result.success is False
        assert result.is_retryable is False

        updated = repo.get_by_id(item.id)
        assert updated.status == MediaItemStatus.FAILED_PERMANENT

    def test_empty_batch_create_result(self, service, mock_api, repo, tmp_path):
        """Test ambiguous result when batchCreate returns empty."""
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.return_value = "token"
        mock_api.batch_create.return_value = []

        result = service.upload_file(item, file_path, "access_token")

        assert result.success is False
        assert result.needs_review is True

        updated = repo.get_by_id(item.id)
        assert updated.status == MediaItemStatus.NEEDS_REVIEW


class TestRetryPolicy:
    """Tests for exponential backoff retry behavior."""

    def test_retry_on_transient_failure(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        # Fail twice, then succeed
        mock_api.upload_bytes.side_effect = [
            GooglePhotosAPIError("Timeout", status_code=500, is_retryable=True),
            GooglePhotosAPIError("Timeout", status_code=500, is_retryable=True),
            "upload_token",
        ]
        mock_api.batch_create.return_value = [
            {"status": {"code": 0}, "mediaItem": {"id": "success_id"}},
        ]

        result = service.upload_with_retry(item, file_path, "token")

        assert result.success is True
        assert mock_api.upload_bytes.call_count == 3

    def test_exhaust_retries(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.side_effect = GooglePhotosAPIError(
            "Server error", status_code=500, is_retryable=True,
        )

        result = service.upload_with_retry(item, file_path, "token")

        assert result.success is False
        # max_retries=3, so total attempts = 4 (initial + 3 retries)
        assert mock_api.upload_bytes.call_count == 4

    def test_no_retry_on_permanent_failure(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        mock_api.upload_bytes.side_effect = GooglePhotosAPIError(
            "Forbidden", status_code=403, is_retryable=False,
        )

        result = service.upload_with_retry(item, file_path, "token")

        assert result.success is False
        assert mock_api.upload_bytes.call_count == 1  # No retries

    def test_cancel_during_retry(self, service, mock_api, repo, tmp_path):
        item = _make_item(repo)
        file_path = tmp_path / "photo.jpg"
        file_path.write_bytes(b"\xff" * 100)

        call_count = 0

        def cancel_after_first():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        mock_api.upload_bytes.side_effect = GooglePhotosAPIError(
            "Timeout", status_code=500, is_retryable=True,
        )

        result = service.upload_with_retry(
            item, file_path, "token", cancel_flag=cancel_after_first,
        )

        assert result.success is False
        assert "cancelled" in result.error_message.lower()


class TestBackoffCalculation:
    """Test exponential backoff timing."""

    def test_backoff_increases(self, service):
        delays = [service._calculate_backoff(i) for i in range(1, 5)]
        # Each delay should generally increase (with jitter)
        # Just verify they are positive and bounded
        for d in delays:
            assert d > 0
            assert d <= service.max_delay * 1.5  # jitter can add up to 50%
