"""Automated UI tests for PhotoPort desktop interface and storage preflight."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from photoport.archives.archive_scanner import ArchiveEntry, ArchiveScanResult
from photoport.config import AppConfig
from photoport.google_photos.quota_service import StorageInfo
from photoport.migration.migration_manager import MigrationManager
from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus
from photoport.ui.main_window import MainWindow


@pytest.fixture
def app(qtbot):
    """Ensure QApplication is active."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path: Path, qtbot):
    """Create a test MainWindow with mock dependencies."""
    # Ensure headless friendly test environment
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    test_db = Database(tmp_path / "ui_test.db")
    config = AppConfig(data_dir=tmp_path / "data", temp_dir=tmp_path / "temp")
    manager = MigrationManager(config=config, db=test_db)

    # Mock OAuth to avoid real keyring / network calls
    mock_oauth = MagicMock()
    mock_oauth.is_authenticated = False
    mock_oauth.user_email = ""
    mock_oauth.get_credentials.return_value = MagicMock(token="fake_token")
    mock_oauth.access_token = "fake_token"

    win = MainWindow(config=config, oauth=mock_oauth, manager=manager)
    qtbot.addWidget(win)
    yield win
    win.thread_pool.waitForDone(3000)
    win.close()
    test_db.close()


def test_ui_initial_state(window: MainWindow):
    """Verify default initial UI state before scanning or connecting."""
    assert "PhotoPort" in window.windowTitle()
    assert "Not connected" in window.account_label.text()
    assert window.switch_btn.isVisible() is False
    assert window.start_btn.isEnabled() is False
    assert window.storage_status_label.text() == "Capacity status: Not checked"


def test_ui_account_connection_display(window: MainWindow):
    """Connecting account updates account label and displays Switch Account button."""
    window.oauth.user_email = "personal.archive@gmail.com"
    window._on_auth_success(None)
    assert "personal.archive@gmail.com" in window.account_label.text()
    assert not window.switch_btn.isHidden()
    assert window._is_connected is True


def test_ui_source_archive_and_folder_selection(window: MainWindow, tmp_path: Path):
    """Selecting ZIP files and extracted folders updates source counts and total size."""
    zip_path = tmp_path / "takeout_test.zip"
    zip_path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # Valid empty zip header (22 bytes)

    folder_path = tmp_path / "ExtractedMedia"
    folder_path.mkdir()
    (folder_path / "img1.jpg").write_bytes(b"\x00" * 1024)

    window._archive_paths = [str(zip_path), str(folder_path)]
    window._update_archive_display()

    assert "2 source(s)" in window.archive_size_label.text()
    assert window.stat_archives._val.text() == "2"
    assert str(zip_path) in window.archive_list.toPlainText()
    assert str(folder_path) in window.archive_list.toPlainText()


def test_ui_scan_results_display(window: MainWindow):
    """Scan completion displays comprehensive metrics and scanning limitations in plain text."""
    scan = ArchiveScanResult()
    scan.media_entries = [
        ArchiveEntry("a.zip", "p1.jpg", "p1.jpg", 1000, True, False, False),
        ArchiveEntry("a.zip", "p2.jpg", "p2.jpg", 2000, True, False, False),
    ]
    scan.duplicate_media_entries = [
        ArchiveEntry("a.zip", "dup.jpg", "dup.jpg", 500, True, False, False),
    ]
    scan.sidecar_entries = [
        ArchiveEntry("a.zip", "p1.jpg.json", "p1.jpg.json", 100, False, True, False),
    ]
    scan.scanning_limitations = [
        "ZIP archives are inspected via central directory headers.",
        "Deduplication compares filename, size, and CRC32.",
    ]
    scan.calculate_metrics()

    window._on_scan_complete(scan)

    text = window.scan_results.toPlainText()
    assert "Media files discovered : 2" in text
    assert "Duplicate entries" in text
    assert "Scanning Limitations & Assumptions:" in text
    assert "ZIP archives are inspected via central directory headers" in text


def test_ui_storage_preflight_enough_enables_start(window: MainWindow):
    """When preflight confirms ENOUGH storage, status displays confirmed and start button is enabled."""
    # Register 1 ready item
    window.manager.media_repo.insert(MediaItem(
        archive_path="a.zip", zip_member_path="pic.jpg", file_name="pic.jpg",
        file_size=10 * 1024**3, status=MediaItemStatus.READY,
    ))
    window._is_connected = True

    window.manager.storage_info = StorageInfo(
        total_bytes=200 * 1024**3, used_bytes=50 * 1024**3, free_bytes=150 * 1024**3, available=True,
    )

    preflight = window.manager.preflight_check()
    window._on_storage_result(preflight)

    assert "Capacity Confirmed" in window.storage_status_label.text()
    assert window.start_btn.isEnabled() is True


def test_ui_storage_preflight_insufficient_disables_start_and_shows_shortfall(window: MainWindow):
    """When preflight confirms INSUFFICIENT storage, status shows shortfall, warnings show options, and start is disabled."""
    # Register 1 ready item (50 GB)
    window.manager.media_repo.insert(MediaItem(
        archive_path="a.zip", zip_member_path="big.jpg", file_name="big.jpg",
        file_size=50 * 1024**3, status=MediaItemStatus.READY,
    ))
    window._is_connected = True

    # Account has only 10 GB free
    window.manager.storage_info = StorageInfo(
        total_bytes=15 * 1024**3, used_bytes=5 * 1024**3, free_bytes=10 * 1024**3, available=True,
    )

    preflight = window.manager.preflight_check()
    window._on_storage_result(preflight)

    assert "Insufficient Storage" in window.storage_status_label.text()
    assert "DESTINATION STORAGE INSUFFICIENT" in window.warnings_label.text()
    assert "Missing Space" in window.warnings_label.text()
    assert "Practical Options:" in window.warnings_label.text()
    assert window.start_btn.isEnabled() is False


def test_ui_storage_preflight_unknown_disables_start(window: MainWindow):
    """When quota is UNKNOWN, UI explains failure, blocks start, and offers retry."""
    window.manager.media_repo.insert(MediaItem(
        archive_path="a.zip", zip_member_path="pic.jpg", file_name="pic.jpg",
        file_size=5 * 1024**3, status=MediaItemStatus.READY,
    ))
    window._is_connected = True

    window.manager.storage_info = StorageInfo(
        available=False, is_unknown=True, error="HTTP 401 Unauthorized",
    )

    preflight = window.manager.preflight_check()
    window._on_storage_result(preflight)

    assert "Capacity Unknown" in window.storage_status_label.text()
    assert "STORAGE CAPACITY UNKNOWN" in window.warnings_label.text()
    assert window.start_btn.isEnabled() is False
