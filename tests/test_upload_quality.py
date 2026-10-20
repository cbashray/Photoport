"""Comprehensive test suite for Upload Quality Selection in PhotoPort.

Tests:
1. UploadQualityMode enum and session persistence in SQLite ledger.
2. MediaConverter: downscaling >16 MP, compression, EXIF preservation, source file invariance.
3. UploadBackend interface isolation: OfficialOriginalBackend, StorageSaverBackend, ExperimentalGpmcBackend.
4. StoragePreflightService integration: mode-aware sizing, safety margins, uncertainty warnings.
5. Migration report generation with quality mode.
6. QualitySelectorWidget UI interactions.
"""

from __future__ import annotations

from pathlib import Path

import piexif
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader

from photoport.config import AppConfig
from photoport.google_photos.backend_interface import (
    ExperimentalGpmcBackend,
    OfficialOriginalBackend,
    StorageSaverBackend,
    get_upload_backend,
)
from photoport.google_photos.quota_service import StorageInfo
from photoport.media.converter import MediaConverter
from photoport.migration.report_generator import ReportGenerator
from photoport.migration.storage_preflight import PreflightStatus, StoragePreflightService
from photoport.storage.database import Database
from photoport.storage.models import (
    MediaItem,
    MediaItemStatus,
    MediaType,
    MigrationSession,
    UploadQualityMode,
)
from photoport.storage.repository import MediaItemRepository, SessionRepository
from photoport.ui.quality_selector import QualitySelectorWidget
from photoport.utils.hashing import sha256_file


@pytest.fixture
def temp_dirs(tmp_path: Path):
    source_dir = tmp_path / "source"
    temp_dir = tmp_path / "temp"
    db_path = tmp_path / "test.db"
    source_dir.mkdir()
    temp_dir.mkdir()
    return {"source": source_dir, "temp": temp_dir, "db": db_path}


def create_test_image(path: Path, width: int, height: int, quality: int = 95) -> None:
    """Helper to create a synthetic JPEG image for testing."""
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.darkCyan)
    img.save(str(path), "JPEG", quality)


# ===========================================================================
# 1. Media Converter Tests
# ===========================================================================


class TestMediaConverter:
    """Tests for local client-side downscaling and compression pipeline."""

    def test_downscales_large_images_over_16mp(self, temp_dirs):
        # 5000 x 4000 = 20 Megapixels
        src = temp_dirs["source"] / "large_20mp.jpg"
        create_test_image(src, 5000, 4000)
        orig_hash = sha256_file(src)
        orig_size = src.stat().st_size

        converter = MediaConverter(max_megapixels=16.0, quality=85)
        res = converter.convert_photo(src, temp_dirs["temp"])

        assert res.converted is True
        assert res.is_downscaled is True
        assert res.output_path.exists()
        assert res.output_path != src

        # Verify output resolution is capped at <= 16 MP
        reader = QImageReader(str(res.output_path))
        img = reader.read()
        pixels = img.width() * img.height()
        assert pixels <= 16_000_000
        assert res.output_size < orig_size
        assert res.savings_bytes > 0
        assert res.savings_ratio > 0.0

        # CRITICAL: Verify source file is 100% untouched and unchanged
        assert sha256_file(src) == orig_hash

        # Cleanup
        if res.output_path.exists():
            res.output_path.unlink()

    def test_preserves_resolution_for_sub_16mp_images(self, temp_dirs):
        # 2000 x 1500 = 3 Megapixels (well below 16 MP cap)
        src = temp_dirs["source"] / "small_3mp.jpg"
        create_test_image(src, 2000, 1500, quality=98)
        orig_hash = sha256_file(src)

        converter = MediaConverter(max_megapixels=16.0, quality=85)
        res = converter.convert_photo(src, temp_dirs["temp"])

        if res.converted:
            assert res.is_downscaled is False
            reader = QImageReader(str(res.output_path))
            img = reader.read()
            assert img.width() == 2000
            assert img.height() == 1500
            res.output_path.unlink()

        # Source file must never be modified
        assert sha256_file(src) == orig_hash

    def test_non_photo_media_passed_through_untouched(self, temp_dirs):
        video_src = temp_dirs["source"] / "sample.mp4"
        video_src.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1000)
        orig_hash = sha256_file(video_src)

        converter = MediaConverter()
        res = converter.convert_photo(video_src, temp_dirs["temp"])

        assert res.converted is False
        assert res.output_path == video_src
        assert sha256_file(video_src) == orig_hash

    def test_preserves_exif_metadata(self, temp_dirs):
        src = temp_dirs["source"] / "photo_with_exif.jpg"
        create_test_image(src, 4500, 4000, quality=95)

        # Inject dummy EXIF tags
        zeroth = {piexif.ImageIFD.Make: b"PhotoPortCamera", piexif.ImageIFD.Model: b"TestModel"}
        exif_dict = {"0th": zeroth, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        piexif.insert(piexif.dump(exif_dict), str(src))

        converter = MediaConverter(max_megapixels=16.0, quality=85)
        res = converter.convert_photo(src, temp_dirs["temp"])

        assert res.converted is True
        loaded = piexif.load(str(res.output_path))
        assert loaded["0th"][piexif.ImageIFD.Make] == b"PhotoPortCamera"
        assert loaded["0th"][piexif.ImageIFD.Model] == b"TestModel"

        if res.output_path.exists():
            res.output_path.unlink()


# ===========================================================================
# 2. Upload Backend Isolation Tests
# ===========================================================================


class TestUploadBackendInterface:
    """Tests isolating official vs storage saver vs experimental backends."""

    def test_official_original_backend(self, temp_dirs):
        backend = OfficialOriginalBackend()
        assert backend.quality_mode == UploadQualityMode.ORIGINAL
        is_avail, desc = backend.is_available()
        assert is_avail is True

        # 100% of original bytes estimated
        assert backend.estimate_upload_size(50_000_000, is_photo=True) == 50_000_000
        assert backend.estimate_upload_size(100_000_000, is_photo=False) == 100_000_000

        # prepare_media returns the source file directly with is_temporary=False
        src = temp_dirs["source"] / "sample.jpg"
        src.write_bytes(b"data")
        prep_path, is_temp = backend.prepare_media(src, temp_dirs["temp"], is_photo=True)
        assert prep_path == src
        assert is_temp is False

    def test_storage_saver_backend(self, temp_dirs):
        cfg = AppConfig(storage_saver_estimated_ratio=0.50)
        backend = StorageSaverBackend(cfg)
        assert backend.quality_mode == UploadQualityMode.STORAGE_SAVER
        is_avail, _ = backend.is_available()
        assert is_avail is True

        # Photo estimated at configured ratio, video at 100%
        assert backend.estimate_upload_size(10_000_000, is_photo=True) == 5_000_000
        assert backend.estimate_upload_size(10_000_000, is_photo=False) == 10_000_000

        # Prepare photo converts to temporary file
        src = temp_dirs["source"] / "sample.jpg"
        create_test_image(src, 3000, 2000)
        prep_path, is_temp = backend.prepare_media(src, temp_dirs["temp"], is_photo=True)
        assert is_temp is True
        assert prep_path.exists()
        assert prep_path != src

        # Cleanup prepared temporary file
        backend.cleanup_prepared(prep_path, is_temporary=True)
        assert not prep_path.exists()

    def test_experimental_gpmc_backend_is_disabled_and_isolated(self, temp_dirs):
        backend = ExperimentalGpmcBackend()
        assert backend.quality_mode == UploadQualityMode.EXPERIMENTAL_GPMC

        # Must NOT be available
        is_avail, reason = backend.is_available()
        assert is_avail is False
        assert "Unavailable" in reason or "Disabled" in reason

        # Capability detection must confirm no supported zero-quota API exists
        caps = backend.detect_capabilities()
        assert caps["has_supported_zero_quota_api"] is False
        assert caps["requires_master_token"] is True
        assert caps["requires_device_spoofing"] is True
        assert caps["violates_terms_of_service"] is True
        assert caps["is_eligible"] is False
        assert caps["eligible_account_types"] == []
        assert caps["recommended_fallback"] == UploadQualityMode.ORIGINAL
        assert len(caps["limitation_reasons"]) >= 4

        # Verify fallback backend returns OfficialOriginalBackend
        assert isinstance(backend.fallback_backend, OfficialOriginalBackend)

        # Calling prepare_media raises NotImplementedError instructing fallback
        src = temp_dirs["source"] / "sample.jpg"
        src.write_bytes(b"data")
        with pytest.raises(NotImplementedError) as exc_info:
            backend.prepare_media(src, temp_dirs["temp"])
        assert "PhotoPort will safely fall back to the supported Original Quality backend" in str(exc_info.value)

    def test_backend_factory(self):
        b1 = get_upload_backend(UploadQualityMode.ORIGINAL)
        assert isinstance(b1, OfficialOriginalBackend)

        b2 = get_upload_backend("storage_saver")
        assert isinstance(b2, StorageSaverBackend)

        b3 = get_upload_backend(UploadQualityMode.EXPERIMENTAL_GPMC)
        assert isinstance(b3, ExperimentalGpmcBackend)


# ===========================================================================
# 3. Session Persistence & SQLite Schema Tests
# ===========================================================================


class TestQualityModePersistence:
    """Tests ensuring selected quality mode is persisted in SQLite and survives app restarts."""

    def test_create_and_load_session_with_quality_mode(self, temp_dirs):
        db = Database(temp_dirs["db"])
        session_repo = SessionRepository(db)

        # Create session with Storage Saver
        session = MigrationSession(
            total_archives=2,
            quality_mode=UploadQualityMode.STORAGE_SAVER,
            destination_account="user@example.com",
        )
        sess_id = session_repo.create(session)
        assert sess_id > 0

        # Retrieve and verify
        loaded = session_repo.get_latest()
        assert loaded is not None
        assert loaded.quality_mode == UploadQualityMode.STORAGE_SAVER
        assert loaded.destination_account == "user@example.com"

        # Update to another quality mode
        loaded.quality_mode = UploadQualityMode.ORIGINAL
        session_repo.update(loaded)

        reloaded = session_repo.get_by_id(sess_id)
        assert reloaded is not None
        assert reloaded.quality_mode == UploadQualityMode.ORIGINAL

        db.close()


# ===========================================================================
# 4. Storage Preflight Service Integration Tests
# ===========================================================================


class TestStoragePreflightQualityIntegration:
    """Tests preflight estimation for each quality mode."""

    def test_preflight_original_quality_estimates_raw_size(self):
        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=100 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            available=True,
        )

        res = service.run_preflight(
            total_scan_bytes=20 * 1024**3,  # 20 GB raw
            storage_info=storage_info,
            quality_mode=UploadQualityMode.ORIGINAL,
            safety_margin_percent=5.0,
            safety_margin_min_bytes=0,
        )

        assert res.quality_mode == UploadQualityMode.ORIGINAL
        assert res.estimated_upload_bytes == 20 * 1024**3
        assert res.total_required_bytes == int(20 * 1024**3 * 1.05)
        assert res.status == PreflightStatus.ENOUGH

    def test_preflight_storage_saver_reduces_estimated_payload(self):
        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=15 * 1024**3,
            used_bytes=5 * 1024**3,
            free_bytes=10 * 1024**3,  # 10 GB free
            available=True,
        )

        # 16 GB raw would not fit in 10 GB with Original Quality,
        # but with Storage Saver (50% ratio = 8 GB + 5% buffer = 8.4 GB), it fits!
        res_orig = service.run_preflight(
            total_scan_bytes=16 * 1024**3,
            storage_info=storage_info,
            quality_mode=UploadQualityMode.ORIGINAL,
            safety_margin_percent=5.0,
            safety_margin_min_bytes=0,
        )
        assert res_orig.status == PreflightStatus.INSUFFICIENT

        res_saver = service.run_preflight(
            total_scan_bytes=16 * 1024**3,
            storage_info=storage_info,
            quality_mode=UploadQualityMode.STORAGE_SAVER,
            storage_saver_estimated_ratio=0.50,
            safety_margin_percent=5.0,
            safety_margin_min_bytes=0,
        )
        assert res_saver.status == PreflightStatus.ENOUGH
        assert res_saver.estimated_upload_bytes == 8 * 1024**3
        # Must clearly disclose that it is NOT quota-free
        assert any("NOT quota-free" in w for w in res_saver.warnings)

    def test_preflight_experimental_gpmc_flags_uncertainty(self):
        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=15 * 1024**3,
            used_bytes=5 * 1024**3,
            free_bytes=10 * 1024**3,
            available=True,
        )

        res = service.run_preflight(
            total_scan_bytes=5 * 1024**3,
            storage_info=storage_info,
            quality_mode=UploadQualityMode.EXPERIMENTAL_GPMC,
        )

        # Preflight must NOT claim the migration will fit for experimental unverified mode
        assert res.status == PreflightStatus.UNKNOWN
        assert res.can_proceed is False
        assert any("Experimental" in w or "unverified" in w for w in res.warnings)


# ===========================================================================
# 5. Migration Report Tests
# ===========================================================================


class TestMigrationReportQualityMode:
    """Tests inclusion of quality mode in migration reports."""

    def test_report_includes_quality_mode(self, temp_dirs):
        db = Database(temp_dirs["db"])
        session_repo = SessionRepository(db)
        media_repo = MediaItemRepository(db)

        session = MigrationSession(
            quality_mode=UploadQualityMode.STORAGE_SAVER,
            destination_account="user@example.com",
            total_archives=1,
            total_files_discovered=1,
        )
        sess_id = session_repo.create(session)
        session.id = sess_id

        item = MediaItem(
            archive_path="test.zip",
            zip_member_path="photo.jpg",
            file_name="photo.jpg",
            file_size=1024,
            media_type=MediaType.PHOTO,
            status=MediaItemStatus.UPLOADED,
        )
        media_repo.insert(item)

        generator = ReportGenerator(db)
        summary = generator.generate_summary(session)
        assert summary["session"]["quality_mode"] == "storage_saver"

        text_report = generator.get_readable_report(session)
        assert "storage_saver" in text_report

        json_path = temp_dirs["temp"] / "report.json"
        generator.export_json(json_path, session)
        assert json_path.exists()
        content = json_path.read_text()
        assert '"quality_mode": "storage_saver"' in content

        db.close()


# ===========================================================================
# 6. Quality Selector UI Tests
# ===========================================================================


class TestQualitySelectorWidget:
    """Tests for the QualitySelectorWidget UI component."""

    def test_quality_selector_defaults_to_original(self, qtbot):
        widget = QualitySelectorWidget()
        qtbot.addWidget(widget)

        assert widget.get_selected_mode() == UploadQualityMode.ORIGINAL

    def test_quality_selector_switch_mode(self, qtbot):
        widget = QualitySelectorWidget()
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.quality_changed, timeout=1000) as blocker:
            widget.set_selected_mode(UploadQualityMode.STORAGE_SAVER)

        assert blocker.args == [UploadQualityMode.STORAGE_SAVER]
        assert widget.get_selected_mode() == UploadQualityMode.STORAGE_SAVER

    def test_quality_selector_rejects_unavailable_zero_quota(self, qtbot):
        widget = QualitySelectorWidget()
        qtbot.addWidget(widget)

        # Attempt to select experimental zero-quota mode programmatically
        widget.set_selected_mode(UploadQualityMode.EXPERIMENTAL_GPMC)

        # Must safely fall back to ORIGINAL because zero-quota is unavailable
        assert widget.get_selected_mode() == UploadQualityMode.ORIGINAL


# ===========================================================================
# 7. Zero-Quota Feasibility & Security Guardrails
# ===========================================================================


class TestZeroQuotaFeasibilityGuardrails:
    """Tests ensuring zero-quota cannot be falsely claimed, master tokens are rejected,

    and OAuth credentials remain strictly protected in the OS keychain.
    """

    def test_oauth_security_preserves_os_keychain(self):
        from unittest.mock import MagicMock, patch

        from photoport.auth.google_oauth import GoogleOAuth

        oauth = GoogleOAuth(credentials_path=Path("credentials.json"))
        # Ensure credentials mechanism relies on standard RFC 6749 PKCE tokens
        assert oauth.scopes == [
            "https://www.googleapis.com/auth/photoslibrary.appendonly",
            "https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        # Verify token storage interacts with keyring
        mock_payload = '{"token": "test-token", "refresh_token": "rt", "client_id": "cid", "client_secret": "cs"}'
        mock_creds = MagicMock(valid=True, expired=False)
        with (
            patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds),
            patch("keyring.get_password", return_value=mock_payload) as mock_get,
        ):
            creds = oauth.get_credentials()
            assert creds is mock_creds
            mock_get.assert_called_once()

    def test_preflight_refuses_to_claim_zero_quota_fits(self):
        service = StoragePreflightService()
        storage_info = StorageInfo(
            total_bytes=100 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            available=True,
        )

        res = service.run_preflight(
            total_scan_bytes=50 * 1024**3,
            storage_info=storage_info,
            quality_mode=UploadQualityMode.EXPERIMENTAL_GPMC,
        )

        # Preflight must NOT claim the migration will fit for experimental zero-quota
        assert res.can_proceed is False
        assert res.status == PreflightStatus.UNKNOWN
        assert any("Experimental" in w or "unverified" in w for w in res.warnings)

    def test_synthetic_media_safety_invariance(self, temp_dirs):
        # Create synthetic fixture media
        synthetic_img = temp_dirs["source"] / "disposable_test.jpg"
        create_test_image(synthetic_img, 1000, 1000)
        orig_hash = sha256_file(synthetic_img)

        # Backend should never modify the fixture
        backend = get_upload_backend(UploadQualityMode.ORIGINAL)
        prep_path, is_temp = backend.prepare_media(synthetic_img, temp_dirs["temp"])
        assert prep_path == synthetic_img
        assert sha256_file(synthetic_img) == orig_hash

