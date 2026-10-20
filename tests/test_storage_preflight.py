"""Tests for upload service with mocked Google API."""

from __future__ import annotations

from pathlib import Path

import pytest

from photoport.google_photos.api_client import GooglePhotosAPIError
from photoport.google_photos.quota_service import StorageInfo
from photoport.storage.database import Database
from photoport.storage.repository import MediaItemRepository


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def repo(db: Database):
    return MediaItemRepository(db)


class TestStoragePreflight:
    """Tests for storage quota checking."""

    def test_sufficient_storage(self):
        info = StorageInfo(
            total_bytes=200 * 1024**3,  # 200 GB
            used_bytes=50 * 1024**3,    # 50 GB
            free_bytes=150 * 1024**3,   # 150 GB
            available=True,
        )
        assert info.can_fit(45 * 1024**3) is True  # 45 GB archive
        assert info.fit_status(45 * 1024**3) == "ENOUGH"

    def test_insufficient_storage(self):
        info = StorageInfo(
            total_bytes=200 * 1024**3,
            used_bytes=180 * 1024**3,
            free_bytes=20 * 1024**3,
            available=True,
        )
        assert info.can_fit(45 * 1024**3) is False
        assert info.fit_status(45 * 1024**3) == "INSUFFICIENT"

    def test_unknown_storage(self):
        info = StorageInfo(available=False, is_unknown=True, error="API error")
        assert info.can_fit(45 * 1024**3) is False
        assert info.fit_status(45 * 1024**3) == "UNKNOWN"

    def test_unmetered_pooled_storage(self):
        """Unmetered or pooled institutional storage must be marked as unknown, not zero or unlimited."""
        info = StorageInfo(
            used_bytes=10 * 1024**3,
            available=False,
            is_unknown=True,
            error="Storage limit is unmetered or not reported",
        )
        assert info.fit_status(5 * 1024**3) == "UNKNOWN"
        assert info.available is False
        assert info.is_unknown is True

    def test_migration_stops_safely_on_insufficient_storage(self, db: Database, tmp_path: Path):
        """MigrationManager must refuse to start if preflight confirms destination cannot fit files."""
        from photoport.config import AppConfig
        from photoport.migration.migration_manager import MigrationManager
        from photoport.storage.models import MediaItem, MediaItemStatus

        repo = MediaItemRepository(db)
        repo.insert(MediaItem(
            archive_path="a.zip", zip_member_path="big.jpg", file_name="big.jpg",
            file_size=50 * 1024**3, status=MediaItemStatus.READY,
        ))

        config = AppConfig(temp_dir=tmp_path)
        manager = MigrationManager(config=config, db=db)

        # Set storage_info with only 20 GB free
        manager.storage_info = StorageInfo(
            total_bytes=100 * 1024**3, used_bytes=80 * 1024**3,
            free_bytes=20 * 1024**3, available=True,
        )

        with pytest.raises(ValueError, match="destination storage is insufficient"):
            manager.start_migration(access_token_provider=lambda: "fake_token")

    def test_usage_percent(self):
        info = StorageInfo(total_bytes=100, used_bytes=75, free_bytes=25, available=True)
        assert info.usage_percent == 75.0

    def test_zero_total(self):
        info = StorageInfo(total_bytes=0, used_bytes=0, free_bytes=0, available=True)
        assert info.usage_percent == 0.0


class TestAPIClientErrors:
    """Test error classification in the API client."""

    def test_api_error_retryable(self):
        err = GooglePhotosAPIError("Rate limited", status_code=429, is_retryable=True)
        assert err.is_retryable is True
        assert err.status_code == 429

    def test_api_error_permanent(self):
        err = GooglePhotosAPIError("Forbidden", status_code=403, is_retryable=False)
        assert err.is_retryable is False
        assert err.status_code == 403

    def test_api_error_default(self):
        err = GooglePhotosAPIError("Something happened")
        assert err.status_code == 0
        assert err.is_retryable is False


class TestStoragePreflightServiceExtended:
    """Comprehensive tests for StoragePreflightService, QuotaService, safety margins, and resumed migrations."""

    def test_preflight_sufficient_capacity(self):
        """Preflight succeeds when available storage safely exceeds payload plus safety margin."""
        from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService

        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=200 * 1024**3,
            used_bytes=50 * 1024**3,
            free_bytes=150 * 1024**3,
            available=True,
            user_email="user@example.com",
        )

        result = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=40 * 1024**3,  # 40 GB
            safety_margin_percent=5.0,
        )

        assert result.status == PreflightStatus.ENOUGH
        assert result.can_proceed is True
        assert result.shortfall_bytes == 0
        assert result.remaining_upload_bytes == 40 * 1024**3
        # 5% of 40 GB is 2 GB (which exceeds 500 MB min margin)
        assert result.safety_margin_bytes == int(40 * 1024**3 * 0.05)
        assert result.total_required_bytes == (40 * 1024**3) + result.safety_margin_bytes

    def test_preflight_insufficient_capacity_with_shortfall(self):
        """Preflight fails with actionable recommendations when payload exceeds free capacity."""
        from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService

        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=15 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=5 * 1024**3,  # 5 GB free
            available=True,
            user_email="free_tier@example.com",
        )

        result = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=20 * 1024**3,  # 20 GB upload
            safety_margin_percent=5.0,
        )

        assert result.status == PreflightStatus.INSUFFICIENT
        assert result.can_proceed is False
        assert result.shortfall_bytes > 0
        expected_shortfall = result.total_required_bytes - (5 * 1024**3)
        assert result.shortfall_bytes == expected_shortfall
        assert len(result.recommendations) >= 3
        assert any("Google One" in r for r in result.recommendations)

    def test_preflight_zero_free_space(self):
        """Zero free bytes immediately flags INSUFFICIENT with shortfall equal to total required."""
        from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService

        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=100 * 1024**3,
            used_bytes=100 * 1024**3,
            free_bytes=0,
            available=True,
        )

        result = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=10 * 1024**3,
        )

        assert result.status == PreflightStatus.INSUFFICIENT
        assert result.can_proceed is False
        assert result.shortfall_bytes == result.total_required_bytes

    def test_preflight_unknown_quota_never_unlimited(self):
        """Failed quota or missing authentication must return UNKNOWN and block proceeding."""
        from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService

        service = StoragePreflightService()
        storage_info = StorageInfo(
            available=False,
            is_unknown=True,
            error="Connection timed out to Google Drive API",
        )

        result = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=5 * 1024**3,
        )

        assert result.status == PreflightStatus.UNKNOWN
        assert result.can_proceed is False
        assert any("UNKNOWN" in w or "timed out" in w for w in result.warnings)
        assert any("Retry" in r for r in result.recommendations)

    def test_preflight_safety_margin_percentage_vs_minimum(self):
        """Safety margin applies the greater of configured percentage or configured minimum byte threshold."""
        from photoport.migration.storage_preflight import StoragePreflightService

        service = StoragePreflightService()
        min_margin_bytes = 500 * 1024 * 1024  # 500 MB

        # Case 1: Small payload (100 MB). 5% is 5 MB, which is less than 500 MB min margin.
        storage_info = StorageInfo(free_bytes=10 * 1024**3, available=True)
        res_small = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=100 * 1024 * 1024,
            safety_margin_percent=5.0,
            safety_margin_min_bytes=min_margin_bytes,
        )
        assert res_small.safety_margin_bytes == min_margin_bytes

        # Case 2: Large payload (50 GB). 5% is 2.5 GB, which exceeds 500 MB.
        res_large = service.run_preflight(
            storage_info=storage_info,
            total_scan_bytes=50 * 1024**3,
            safety_margin_percent=5.0,
            safety_margin_min_bytes=min_margin_bytes,
        )
        assert res_large.safety_margin_bytes == int(50 * 1024**3 * 0.05)

    def test_preflight_resumed_migration_excludes_already_uploaded(self, repo: MediaItemRepository):
        """Resumed migrations must evaluate only remaining items and exclude already uploaded files."""
        from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService
        from photoport.storage.models import MediaItem, MediaItemStatus

        # Insert 4 uploaded items (4 x 1 GB = 4 GB)
        for i in range(4):
            repo.insert(MediaItem(
                archive_path="archive.zip", zip_member_path=f"uploaded_{i}.jpg",
                file_name=f"uploaded_{i}.jpg", file_size=1 * 1024**3,
                status=MediaItemStatus.UPLOADED, google_media_id=f"g_id_{i}",
            ))

        # Insert 2 ready items (2 x 1 GB = 2 GB)
        for i in range(2):
            repo.insert(MediaItem(
                archive_path="archive.zip", zip_member_path=f"ready_{i}.jpg",
                file_name=f"ready_{i}.jpg", file_size=1 * 1024**3,
                status=MediaItemStatus.READY,
            ))

        service = StoragePreflightService()

        # Destination has 3 GB free.
        # Total archive is 6 GB (would NOT fit 3 GB if treated as new).
        # Remaining upload is only 2 GB (+ 500 MB safety buffer = 2.5 GB, which DOES fit 3 GB).
        storage_info = StorageInfo(
            total_bytes=15 * 1024**3,
            used_bytes=12 * 1024**3,
            free_bytes=3 * 1024**3,
            available=True,
        )

        result = service.run_preflight(
            media_repo=repo,
            storage_info=storage_info,
        )

        assert result.is_resumed_migration is True
        assert result.already_uploaded_items_count == 4
        assert result.already_uploaded_bytes == 4 * 1024**3
        assert result.remaining_items_count == 2
        assert result.remaining_upload_bytes == 2 * 1024**3
        assert result.status == PreflightStatus.ENOUGH
        assert result.can_proceed is True

    def test_preflight_resumed_migration_ambiguous_in_flight_counted_conservatively(self, repo: MediaItemRepository):
        """Ambiguous in-flight items (NEEDS_REVIEW or UPLOADING) are conservatively counted in remaining upload."""
        from photoport.migration.storage_preflight import StoragePreflightService
        from photoport.storage.models import MediaItem, MediaItemStatus

        # 3 uploaded items (3 GB)
        for i in range(3):
            repo.insert(MediaItem(
                archive_path="a.zip", zip_member_path=f"up_{i}.jpg", file_name=f"up_{i}.jpg",
                file_size=1 * 1024**3, status=MediaItemStatus.UPLOADED,
            ))

        # 1 ambiguous item in NEEDS_REVIEW (1 GB)
        repo.insert(MediaItem(
            archive_path="a.zip", zip_member_path="ambig.jpg", file_name="ambig.jpg",
            file_size=1 * 1024**3, status=MediaItemStatus.NEEDS_REVIEW, upload_token="tok123",
        ))

        # 1 pending item in READY (1 GB)
        repo.insert(MediaItem(
            archive_path="a.zip", zip_member_path="ready.jpg", file_name="ready.jpg",
            file_size=1 * 1024**3, status=MediaItemStatus.READY,
        ))

        service = StoragePreflightService()
        storage_info = StorageInfo(free_bytes=10 * 1024**3, available=True)

        result = service.run_preflight(
            media_repo=repo,
            storage_info=storage_info,
        )

        assert result.ambiguous_items_count == 1
        assert result.ambiguous_bytes == 1 * 1024**3
        # Remaining upload must include the 1 GB ready AND 1 GB ambiguous = 2 GB total
        assert result.remaining_upload_bytes == 2 * 1024**3
        assert any("conservatively" in w for w in result.warnings)

    def test_quota_service_parses_account_identity_and_storage(self, monkeypatch):
        """QuotaService parses user email, display name, and quota from Google Drive API."""
        from unittest.mock import MagicMock

        import requests

        from photoport.google_photos.quota_service import QuotaService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "user": {
                "displayName": "Alex Developer",
                "emailAddress": "alex.dev@gmail.com",
            },
            "storageQuota": {
                "limit": str(200 * 1024**3),
                "usage": str(50 * 1024**3),
                "usageInDrive": str(20 * 1024**3),
                "usageInDriveTrash": "0",
            },
        }

        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: mock_resp)

        svc = QuotaService()
        info = svc.get_storage_info(access_token="test_mock_token")

        assert info.available is True
        assert info.is_unknown is False
        assert info.user_email == "alex.dev@gmail.com"
        assert info.display_name == "Alex Developer"
        assert info.total_bytes == 200 * 1024**3
        assert info.used_bytes == 50 * 1024**3
        assert info.free_bytes == 150 * 1024**3
        assert info.drive_usage_bytes == 20 * 1024**3

    def test_quota_service_handles_unmetered_limit(self, monkeypatch):
        """QuotaService marks unmetered or missing limit as UNKNOWN, never unlimited."""
        from unittest.mock import MagicMock

        import requests

        from photoport.google_photos.quota_service import QuotaService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "user": {"emailAddress": "org@workplace.edu"},
            "storageQuota": {
                "limit": "-1",
                "usage": "1000000",
            },
        }

        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: mock_resp)

        svc = QuotaService()
        info = svc.get_storage_info(access_token="test_token")

        assert info.available is False
        assert info.is_unknown is True
        assert "unmetered" in info.error.lower()

    def test_quota_service_http_errors_return_unknown(self, monkeypatch):
        """HTTP errors from Drive API return UNKNOWN storage."""
        from unittest.mock import MagicMock

        import requests

        from photoport.google_photos.quota_service import QuotaService

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: mock_resp)

        svc = QuotaService()
        info = svc.get_storage_info(access_token="test_token")

        assert info.available is False
        assert info.is_unknown is True
        assert "403" in info.error

    def test_storage_drops_between_preflight_and_upload_blocks_start(self, db: Database, tmp_path: Path):
        """If storage drops between initial preflight and upload kickoff, start_migration rechecks and blocks upload."""
        from photoport.config import AppConfig
        from photoport.migration.migration_manager import MigrationManager
        from photoport.storage.models import MediaItem, MediaItemStatus

        repo = MediaItemRepository(db)
        repo.insert(MediaItem(
            archive_path="archive.zip", zip_member_path="photo.jpg", file_name="photo.jpg",
            file_size=5 * 1024**3, status=MediaItemStatus.READY,
        ))

        config = AppConfig(temp_dir=tmp_path)
        manager = MigrationManager(config=config, db=db)

        # Preflight initially ran when 20 GB was free
        manager.storage_info = StorageInfo(
            total_bytes=100 * 1024**3, used_bytes=80 * 1024**3,
            free_bytes=20 * 1024**3, available=True,
        )

        # But destination storage dropped to only 2 GB free (shortfall of >3 GB)
        manager.storage_info = StorageInfo(
            total_bytes=100 * 1024**3, used_bytes=98 * 1024**3,
            free_bytes=2 * 1024**3, available=True,
        )

        with pytest.raises(ValueError, match="destination storage is insufficient"):
            manager.start_migration(access_token_provider=lambda: "token")


