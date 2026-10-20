"""Tests for new modular UI components, views, and theme engine."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from photoport.config import AppConfig
from photoport.storage.database import Database
from photoport.storage.models import (
    MediaItem,
    MediaItemStatus,
    MediaType,
    MigrationSession,
    UploadQualityMode,
)
from photoport.storage.repository import MediaItemRepository, SessionRepository
from photoport.ui.components.error_banner import ErrorBanner
from photoport.ui.components.quota_bar import QuotaBarWidget
from photoport.ui.components.stat_card import StatCard
from photoport.ui.components.status_badge import StatusBadge
from photoport.ui.theme import generate_stylesheet, get_palette
from photoport.ui.views.history_view import HistoryView
from photoport.ui.views.inventory_view import InventoryView
from photoport.ui.views.review_view import ReviewView
from photoport.ui.views.settings_view import SettingsView
from photoport.ui.views.sources_view import SourcesView


@pytest.fixture
def app(qtbot):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication([])


def test_theme_generation():
    """Verify dark and light stylesheets are generated without errors."""
    dark_css = generate_stylesheet("dark")
    light_css = generate_stylesheet("light")
    assert "#0f172a" in dark_css
    assert "#f8fafc" in light_css
    assert get_palette("dark").primary == "#2563eb"
    assert get_palette("light").primary == "#2563eb"


def test_stat_card(qtbot):
    """Test StatCard value setting, reading, and backward compatibility."""
    card = StatCard(value=42, label="Photos", icon="🖼️")
    qtbot.addWidget(card)
    assert card.value() == "42"
    assert card._val.text() == "42"

    card.set_value(100)
    assert card.value() == "100"
    assert card._val.text() == "100"


def test_quota_bar_widget(qtbot):
    """Test QuotaBarWidget metric assignment."""
    bar = QuotaBarWidget()
    qtbot.addWidget(bar)

    bar.set_storage_data(
        total_bytes=100 * 1024**3,
        used_bytes=20 * 1024**3,
        required_bytes=10 * 1024**3,
        buffer_bytes=5 * 1024**3,
    )
    assert "used" in bar.summary_label.text()
    assert bar.bar.total_bytes == 100 * 1024**3


def test_status_badge(qtbot):
    """Test StatusBadge rendering for various statuses."""
    b1 = StatusBadge("READY")
    qtbot.addWidget(b1)
    assert "Ready" in b1.text()

    b2 = StatusBadge("NEEDS_REVIEW")
    qtbot.addWidget(b2)
    assert "Needs Review" in b2.text()


def test_error_banner(qtbot):
    """Test ErrorBanner questions structure."""
    banner = ErrorBanner(
        banner_type="warning",
        title="Rate Limit Exceeded",
        what_happened="Google Photos API returned HTTP 429",
        what_it_means="Uploads are paused temporarily",
        what_to_do="Wait 60 seconds before resuming",
        action_text="Resume",
        action_id="resume_op",
    )
    qtbot.addWidget(banner)
    assert "Rate Limit Exceeded" in banner.header_label.text()
    assert "What happened" in banner.body_label.text()
    assert "Impact on media" in banner.body_label.text()
    assert "Recommended action" in banner.body_label.text()


def test_sources_view(tmp_path: Path, qtbot):
    """Test SourcesView add, get, and clear."""
    view = SourcesView()
    qtbot.addWidget(view)

    f1 = tmp_path / "takeout1.zip"
    f1.write_bytes(b"PK")
    f2 = tmp_path / "takeout2.zip"
    f2.write_bytes(b"PK")

    view.add_sources([str(f1), str(f2)])
    assert len(view.get_sources()) == 2
    assert "2 source(s)" in view.archive_size_label.text()

    view.clear_sources()
    assert len(view.get_sources()) == 0


def test_review_view(qtbot):
    """Test ReviewView summary presentation."""
    view = ReviewView()
    qtbot.addWidget(view)

    view.update_summary(
        sources_count=3,
        sources_size_str="15.2 GB",
        account_email="test@example.com",
        quality_mode_str="Storage Saver",
        estimated_payload_str="8.1 GB",
        photos_count=1200,
        videos_count=45,
        duplicates_count=12,
        preflight_confirmed=True,
        can_proceed=True,
    )
    assert "test@example.com" in view.val_account.text()
    assert "Storage Saver" in view.val_quality.text()
    assert "1,200 photos" in view.val_photos.text()
    assert view.start_btn.isEnabled() is True


def test_inventory_view(tmp_path: Path, qtbot):
    """Test InventoryView table population and search filtering."""
    db = Database(tmp_path / "inv_test.db")
    repo = MediaItemRepository(db)

    item1 = MediaItem(
        archive_path="takeout_part1.zip",
        zip_member_path="Photos/summer_vacation.jpg",
        file_name="summer_vacation.jpg",
        file_size=2048,
        media_type=MediaType.PHOTO,
        status=MediaItemStatus.READY,
    )
    item2 = MediaItem(
        archive_path="takeout_part2.zip",
        zip_member_path="Photos/winter_cabin.jpg",
        file_name="winter_cabin.jpg",
        file_size=4096,
        media_type=MediaType.PHOTO,
        status=MediaItemStatus.UPLOADED,
    )
    repo.insert(item1)
    repo.insert(item2)

    view = InventoryView()
    qtbot.addWidget(view)
    view.set_repository(repo)

    assert view.table.rowCount() == 2

    # Filter by search
    view.search_input.setText("summer")
    assert view.table.rowCount() == 1
    assert view.table.item(0, 0).text() == "summer_vacation.jpg"

    # Reset search
    view.search_input.setText("")
    assert view.table.rowCount() == 2
    db.close()


def test_history_view(tmp_path: Path, qtbot):
    """Test HistoryView session listing."""
    db = Database(tmp_path / "hist_test.db")
    repo = SessionRepository(db)

    sess = MigrationSession(
        total_archives=2,
        total_files_discovered=10,
        total_uploaded=10,
        destination_account="archive.user@gmail.com",
        quality_mode=UploadQualityMode.ORIGINAL,
    )
    repo.create(sess)

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_repository(repo)

    assert view.table.rowCount() == 1
    assert "archive.user@gmail.com" in view.table.item(0, 2).text()
    db.close()


def test_settings_view(tmp_path: Path, qtbot):
    """Test SettingsView buffer margin change and theme signaling."""
    cfg = AppConfig(data_dir=tmp_path / "data", temp_dir=tmp_path / "temp")
    view = SettingsView(cfg)
    qtbot.addWidget(view)

    with qtbot.waitSignal(view.theme_changed, timeout=1000) as blocker:
        view.theme_combo.setCurrentIndex(1)
    assert blocker.args == ["light"]

    view.spin_margin.setValue(10.0)
    assert cfg.storage_safety_margin_percent == 10.0
