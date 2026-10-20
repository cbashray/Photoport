"""Main application window — PhotoPort desktop interface.

Integrates dedicated views for Overview, Sources, Storage Preflight,
Quality Selection, Review, Active Migration, Inventory, History,
Settings, and Execution Logs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from photoport import __app_name__, __version__
from photoport.auth.google_oauth import GoogleOAuth
from photoport.config import AppConfig, get_config
from photoport.migration.migration_manager import MigrationManager
from photoport.migration.report_generator import ReportGenerator
from photoport.storage.models import UploadQualityMode
from photoport.ui.quality_selector import QualitySelectorWidget
from photoport.ui.theme import generate_stylesheet
from photoport.ui.views.history_view import HistoryView
from photoport.ui.views.inventory_view import InventoryView
from photoport.ui.views.overview_view import OverviewView
from photoport.ui.views.preflight_view import PreflightView
from photoport.ui.views.progress_view import ProgressView
from photoport.ui.views.review_view import ReviewView
from photoport.ui.views.settings_view import SettingsView
from photoport.ui.views.sources_view import SourcesView
from photoport.ui.workers import ProgressWorker, Worker
from photoport.utils.disk_space import format_bytes
from photoport.utils.logging_config import setup_logging

logger = logging.getLogger("photoport.ui.main_window")


class MainWindow(QMainWindow):
    """PhotoPort main desktop window orchestrating multi-step migration workflow."""

    def __init__(
        self,
        config: AppConfig | None = None,
        oauth: GoogleOAuth | None = None,
        manager: MigrationManager | None = None,
    ) -> None:
        super().__init__()
        self.config = config or get_config()
        self.logger = setup_logging(self.config.log_dir, self.config.log_level)

        # Core services
        self.oauth = oauth or GoogleOAuth(self.config.credentials_path, self.config.token_path)
        self.manager = manager or MigrationManager(self.config)
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)

        # State
        self._archive_paths: list[str] = []
        self._is_connected = False
        self._current_theme = "dark"

        # Window configuration
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(1080, 720)
        self.resize(1260, 840)
        self.setStyleSheet(generate_stylesheet(self._current_theme))

        self._build_menu_bar()
        self._build_ui()
        self._build_status_bar()

        # Periodic refresh timer for migration progress
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh_stats)
        self._update_timer.setInterval(1500)

        # Check initial auth state
        self._check_auth_state()

    # ------------------------------------------------------------------
    # Menu Bar
    # ------------------------------------------------------------------

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction("Open Archives...", self._open_archives)
        file_menu.addAction("Open Archive Folder...", self._open_archive_folder)
        file_menu.addSeparator()
        file_menu.addAction("Export Report (JSON)...", self._export_json)
        file_menu.addAction("Export Report (CSV)...", self._export_csv)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        account_menu = menu_bar.addMenu("&Account")
        account_menu.addAction("Connect Google Account", self._connect_account)
        account_menu.addAction("Disconnect", self._disconnect_account)
        account_menu.addSeparator()
        account_menu.addAction("Check Storage", self._check_storage)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction("Overview", lambda: self.tabs.setCurrentIndex(0))
        view_menu.addAction("Sources & Scan", lambda: self.tabs.setCurrentIndex(1))
        view_menu.addAction("Account & Preflight", lambda: self.tabs.setCurrentIndex(2))
        view_menu.addAction("Upload Quality", lambda: self.tabs.setCurrentIndex(3))
        view_menu.addAction("Migration Review", lambda: self.tabs.setCurrentIndex(4))
        view_menu.addAction("Active Migration", lambda: self.tabs.setCurrentIndex(5))
        view_menu.addAction("File Inventory", lambda: self.tabs.setCurrentIndex(6))
        view_menu.addAction("Migration History", lambda: self.tabs.setCurrentIndex(7))

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction("About", self._show_about)

    # ------------------------------------------------------------------
    # Main UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 10, 16, 10)
        main_layout.setSpacing(10)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(12)

        title = QLabel(f"⚡ {__app_name__}")
        title.setObjectName("header_label")
        header.addWidget(title)

        tagline = QLabel("• Takeout Migration Utility")
        tagline.setObjectName("sub_label")
        header.addWidget(tagline)
        header.addStretch()

        self.header_account_label = QLabel("Not connected")
        self.header_account_label.setObjectName("sub_label")
        header.addWidget(self.header_account_label)

        self.connect_btn = QPushButton("Connect Account")
        self.connect_btn.setObjectName("primary_button")
        self.connect_btn.clicked.connect(self._connect_account)
        header.addWidget(self.connect_btn)

        self.switch_btn = QPushButton("Switch Account")
        self.switch_btn.setObjectName("secondary_button")
        self.switch_btn.clicked.connect(self._switch_account)
        self.switch_btn.setVisible(False)
        header.addWidget(self.switch_btn)

        main_layout.addLayout(header)

        # Main Navigation Tabs
        self.tabs = QTabWidget()

        # 0. Overview
        self.overview_view = OverviewView()
        self.overview_view.navigate_requested.connect(self.tabs.setCurrentIndex)
        self.overview_view.start_migration_requested.connect(self._start_migration)
        self.tabs.addTab(self.overview_view, "🏠 Overview")

        # 1. Sources & Scan
        self.sources_view = SourcesView()
        self.sources_view.open_zips_requested.connect(self._open_archives)
        self.sources_view.open_folder_requested.connect(self._open_archive_folder)
        self.sources_view.scan_requested.connect(self._scan_archives)
        self.sources_view.sources_changed.connect(self._on_sources_changed)
        self.tabs.addTab(self.sources_view, "📁 Sources")

        # 2. Account & Storage Preflight
        self.preflight_view = PreflightView()
        self.preflight_view.connect_account_requested.connect(self._connect_account)
        self.preflight_view.switch_account_requested.connect(self._switch_account)
        self.preflight_view.recheck_storage_requested.connect(self._check_storage)
        self.tabs.addTab(self.preflight_view, "☁️ Preflight")

        # 3. Quality Selection
        self.quality_tab = QWidget()
        q_tab_layout = QVBoxLayout(self.quality_tab)
        q_tab_layout.setContentsMargins(16, 14, 16, 14)
        self.quality_selector = QualitySelectorWidget()
        self.quality_selector.quality_changed.connect(self._on_quality_mode_changed)
        q_tab_layout.addWidget(self.quality_selector)
        q_tab_layout.addStretch()
        self.tabs.addTab(self.quality_tab, "⚡ Quality")

        # 4. Review
        self.review_view = ReviewView()
        self.review_view.start_migration_requested.connect(self._start_migration)
        self.review_view.recheck_requested.connect(self._check_storage)
        self.tabs.addTab(self.review_view, "📋 Review")

        # 5. Migration Execution
        self.progress_view = ProgressView()
        self.progress_view.pause_toggled.connect(self._toggle_pause)
        self.progress_view.cancel_requested.connect(self._cancel_migration)
        self.progress_view.retry_requested.connect(self._retry_failed)
        self.progress_view.review_requested.connect(self._review_ambiguous_items)
        self.progress_view.view_report_requested.connect(self._view_report)
        self.tabs.addTab(self.progress_view, "🚀 Migration")

        # 6. File Inventory
        self.inventory_view = InventoryView()
        self.inventory_view.set_repository(self.manager.media_repo)
        self.inventory_view.refresh_requested.connect(self.inventory_view.reload_data)
        self.tabs.addTab(self.inventory_view, "📑 Inventory")

        # 7. History
        self.history_view = HistoryView()
        self.history_view.set_repository(self.manager.session_repo)
        self.history_view.view_report_requested.connect(self._view_historical_report)
        self.tabs.addTab(self.history_view, "📜 History")

        # 8. Settings
        self.settings_view = SettingsView(self.config)
        self.settings_view.theme_changed.connect(self._on_theme_changed)
        self.settings_view.clear_cache_requested.connect(self._clear_cache)
        self.tabs.addTab(self.settings_view, "⚙️ Settings")

        # 9. Execution Log
        self.tabs.addTab(self._build_log_tab(), "📋 Log")

        main_layout.addWidget(self.tabs)

        # Establish aliases for backwards-compatibility with test suites
        self._bind_test_aliases()

    def _bind_test_aliases(self) -> None:
        """Expose direct attributes on MainWindow required by existing test harness."""
        # Account
        self.account_label = self.preflight_view.account_label

        # Sources
        self.archive_size_label = self.sources_view.archive_size_label
        self.archive_list = self.sources_view.archive_list
        self.scan_results = self.sources_view.scan_results
        self.scan_btn = self.sources_view.scan_btn

        # Preflight & Storage
        self.storage_status_label = self.preflight_view.storage_status_label
        self.storage_total_label = self.preflight_view.storage_total_label
        self.storage_used_label = self.preflight_view.storage_used_label
        self.storage_free_label = self.preflight_view.storage_free_label
        self.storage_required_label = self.preflight_view.storage_required_label
        self.retry_storage_btn = self.preflight_view.retry_storage_btn
        self.warnings_label = self.preflight_view.warnings_label

        # Overview Stats
        self.stat_archives = self.overview_view.stat_archives
        self.stat_total = self.overview_view.stat_total
        self.stat_photos = self.overview_view.stat_photos
        self.stat_videos = self.overview_view.stat_videos
        self.stat_uploaded = self.overview_view.stat_uploaded
        self.stat_failed = self.overview_view.stat_failed
        self.stat_skipped = self.overview_view.stat_skipped
        self.stat_pending = self.overview_view.stat_pending
        self.stat_review = self.overview_view.stat_review

        # Migration & Progress
        self.start_btn = self.review_view.start_btn
        self.progress_bar = self.progress_view.progress_bar
        self.phase_label = self.progress_view.phase_label
        self.current_file_label = self.progress_view.current_file_label
        self.speed_label = self.progress_view.speed_label
        self.eta_label = self.progress_view.eta_label
        self.pause_btn = self.progress_view.pause_btn
        self.cancel_btn = self.progress_view.cancel_btn
        self.review_btn = self.progress_view.review_btn
        self.retry_btn = self.progress_view.retry_btn
        self.view_report_btn = self.progress_view.view_report_btn
        self.migration_log = self.progress_view.migration_log

    # ------------------------------------------------------------------
    # Log Tab
    # ------------------------------------------------------------------

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 14, 16, 14)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("Detailed application logs will appear here.")
        layout.addWidget(self.log_display)

        self._log_handler = _QtLogHandler(self.log_display)
        logging.getLogger("photoport").addHandler(self._log_handler)
        return tab

    # ------------------------------------------------------------------
    # Status Bar
    # ------------------------------------------------------------------

    def _build_status_bar(self) -> None:
        self.status_bar = self.statusBar()
        self.status_bar.showMessage(f"{__app_name__} v{__version__} — Ready")

    # ------------------------------------------------------------------
    # Authentication Actions & Handlers
    # ------------------------------------------------------------------

    def _check_auth_state(self) -> None:
        """Check initial OAuth state."""
        if self.oauth.is_authenticated:
            self._is_connected = True
            email = self.oauth.user_email
            display_text = f"✅ {email}" if email else "✅ Connected"
            self.account_label.setText(display_text)
            self.header_account_label.setText(display_text)
            self.connect_btn.setText("Disconnect")
            self.preflight_view.connect_btn.setText("Disconnect")
            self.switch_btn.setVisible(True)
            self.preflight_view.switch_btn.setVisible(True)
            self.status_bar.showMessage(
                f"Connected to {email}" if email else "Connected to Google account"
            )
            self._check_storage()
        else:
            self._is_connected = False
            self.account_label.setText("⚪ Not connected")
            self.header_account_label.setText("⚪ Not connected")
            self.connect_btn.setText("Connect Account")
            self.preflight_view.connect_btn.setText("Connect Account")
            self.switch_btn.setVisible(False)
            self.preflight_view.switch_btn.setVisible(False)

    def _connect_account(self) -> None:
        """Start OAuth flow or disconnect."""
        if self._is_connected:
            self._disconnect_account()
            return

        if not self.config.credentials_path.exists():
            QMessageBox.critical(
                self,
                "Missing Credentials",
                f"OAuth credentials file not found:\n{self.config.credentials_path}\n\n"
                "Download it from Google Cloud Console → APIs & Services → Credentials.\n"
                "Save it as 'credentials.json' in the application directory.",
            )
            return

        self.status_bar.showMessage("Opening browser for Google sign-in...")
        worker = Worker(self.oauth.authenticate)
        worker.signals.result.connect(self._on_auth_success)
        worker.signals.error.connect(self._on_auth_error)
        self.thread_pool.start(worker)

    def _switch_account(self) -> None:
        """Switch Google account."""
        reply = QMessageBox.question(
            self,
            "Switch Account",
            "Switch Google account?\n\nThis will disconnect the currently connected account and open your browser to select your intended account.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.status_bar.showMessage(
                "Switching account... Please select your account in the browser."
            )
            worker = Worker(self.oauth.switch_account)
            worker.signals.result.connect(self._on_auth_success)
            worker.signals.error.connect(self._on_auth_error)
            self.thread_pool.start(worker)

    def _on_auth_success(self, creds: object) -> None:
        self._is_connected = True
        email = self.oauth.user_email
        display_text = f"✅ {email}" if email else "✅ Connected"
        self.account_label.setText(display_text)
        self.header_account_label.setText(display_text)
        self.connect_btn.setText("Disconnect")
        self.preflight_view.connect_btn.setText("Disconnect")
        self.switch_btn.setVisible(True)
        self.preflight_view.switch_btn.setVisible(True)
        self.status_bar.showMessage(
            f"Successfully connected to {email}" if email else "Connected to Google account"
        )
        self._update_start_button()
        self._check_storage()

    def _on_auth_error(self, error: str) -> None:
        QMessageBox.warning(self, "Authentication Failed", f"Could not sign in:\n{error}")
        self.status_bar.showMessage("Authentication failed")

    def _disconnect_account(self) -> None:
        reply = QMessageBox.question(
            self,
            "Disconnect",
            "Disconnect from Google account? This will clear stored credentials.",
        )
        if reply == QMessageBox.Yes:
            self.oauth.disconnect()
            self._is_connected = False
            self.account_label.setText("⚪ Not connected")
            self.header_account_label.setText("⚪ Not connected")
            self.connect_btn.setText("Connect Account")
            self.preflight_view.connect_btn.setText("Connect Account")
            self.switch_btn.setVisible(False)
            self.preflight_view.switch_btn.setVisible(False)
            self.storage_total_label.setText("—")
            self.storage_used_label.setText("—")
            self.storage_free_label.setText("—")
            self.storage_status_label.setText("Connect your Google account to verify destination storage.")
            self.preflight_view.quota_bar.set_storage_data(0, 0, 0, 0)
            self.status_bar.showMessage("Disconnected")
            self._update_start_button()

    # ------------------------------------------------------------------
    # Source Archive Actions
    # ------------------------------------------------------------------

    def _open_archives(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Takeout ZIP Archives", "", "ZIP Archives (*.zip)"
        )
        if files:
            self._archive_paths.extend(files)
            self._archive_paths = list(set(self._archive_paths))
            self.sources_view.set_sources(self._archive_paths)
            self._update_archive_display()

    def _open_archive_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with Archives or Extracted Media"
        )
        if folder:
            p = Path(folder)
            zips = list(p.glob("*.zip"))
            if zips:
                self._archive_paths.extend(str(z) for z in zips)
            else:
                self._archive_paths.append(str(p))
            self._archive_paths = list(set(self._archive_paths))
            self.sources_view.set_sources(self._archive_paths)
            self._update_archive_display()

    def _on_sources_changed(self, sources: list[str]) -> None:
        self._archive_paths = list(sources)
        self._update_archive_display()

    def _update_archive_display(self) -> None:
        import os
        total_size = 0
        for p in self._archive_paths:
            if os.path.isfile(p):
                total_size += os.path.getsize(p)
            elif os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        total_size += os.path.getsize(os.path.join(root, f))

        self.sources_view.set_sources(self._archive_paths)
        self.archive_list.setPlainText("\n".join(self._archive_paths))
        self.archive_size_label.setText(
            f"{len(self._archive_paths)} source(s) • {format_bytes(total_size)}"
        )
        self.stat_archives._val.setText(str(len(self._archive_paths)))
        self._update_start_button()

    # ------------------------------------------------------------------
    # Scanning Actions & Handlers
    # ------------------------------------------------------------------

    def _scan_archives(self) -> None:
        if not self._archive_paths:
            QMessageBox.information(self, "No Archives", "Please add archives first.")
            return

        self.scan_btn.setEnabled(False)
        self.scan_results.setPlainText("Scanning archives and estimating payload...")
        self.status_bar.showMessage("Scanning archives and estimating payload...")

        worker = Worker(self.manager.scan_archives, self._archive_paths)
        worker.signals.result.connect(self._on_scan_complete)
        worker.signals.error.connect(self._on_scan_error)
        self.thread_pool.start(worker)

    def _on_scan_complete(self, result: object) -> None:
        self.scan_btn.setEnabled(True)
        scan = result

        lines = [
            "✅ Scan complete!",
            "",
            f"📸 Media files discovered : {scan.total_media_count}",
            f"✨ Eligible for upload    : {scan.eligible_media_count} ({format_bytes(scan.eligible_media_bytes)})",
            f"🔄 Duplicate entries      : {scan.total_duplicate_count} ({format_bytes(scan.duplicate_media_bytes)})",
            f"⚠️ Oversized files        : {scan.total_oversized_count} ({format_bytes(scan.oversized_media_bytes)})",
            f"📝 Sidecar JSON metadata  : {scan.total_sidecar_count}",
            f"❓ Unsupported files      : {scan.total_unsupported_count}",
            f"💾 Raw media total size   : {format_bytes(scan.total_media_bytes)}",
        ]

        if scan.scanning_limitations:
            lines.extend(["", "ℹ️ Scanning Limitations & Assumptions:"])
            for lim in scan.scanning_limitations:
                lines.append(f"  • {lim}")

        if scan.errors:
            lines.extend(["", "⚠️ Errors:"])
            for err in scan.errors[:20]:
                lines.append(f"  • {err}")
            if len(scan.errors) > 20:
                lines.append(f"  ... and {len(scan.errors) - 20} more")

        self.scan_results.setPlainText("\n".join(lines))

        # Update stats
        counts = self.manager.media_repo.count_by_status()
        total = self.manager.media_repo.total_count()
        self.stat_total._val.setText(str(total))
        self.stat_pending._val.setText(
            str(counts.get("DISCOVERED", 0) + counts.get("READY", 0))
        )
        self.stat_skipped._val.setText(str(counts.get("SKIPPED", 0)))

        # Update photos / videos breakdown
        photos_c = len([e for e in getattr(scan, "media_entries", []) if getattr(e, "is_photo", True)])
        videos_c = len([e for e in getattr(scan, "media_entries", []) if not getattr(e, "is_photo", True)])
        self.stat_photos._val.setText(str(photos_c))
        self.stat_videos._val.setText(str(videos_c))

        self.inventory_view.reload_data()
        self.status_bar.showMessage(
            f"Scan complete: {scan.eligible_media_count} eligible media files ({format_bytes(scan.eligible_media_bytes)})"
        )

        if self._is_connected:
            self._check_storage()
        self._update_start_button()

    def _on_scan_error(self, error: str) -> None:
        self.scan_btn.setEnabled(True)
        self.scan_results.setPlainText(f"❌ Scan failed:\n{error}")
        self.status_bar.showMessage("Scan failed")

    # ------------------------------------------------------------------
    # Storage Preflight Actions & Handlers
    # ------------------------------------------------------------------

    def _check_storage(self) -> None:
        if not self._is_connected:
            self.storage_status_label.setText("Connect your Google account to verify destination storage.")
            return

        self.status_bar.showMessage("Running storage preflight check...")

        def check():
            token = self.oauth.access_token
            if not token:
                raise ValueError("No access token available")
            selected_mode = self.quality_selector.get_selected_mode()
            return self.manager.preflight_check(token, quality_mode=selected_mode)

        worker = Worker(check)
        worker.signals.result.connect(self._on_storage_result)
        worker.signals.error.connect(lambda e: self._on_storage_error(str(e)))
        self.thread_pool.start(worker)

    def _on_storage_error(self, error: str) -> None:
        self.storage_status_label.setText(f"⚠️ Preflight error: {error}")
        self.warnings_label.setText(
            f"⚠️ Storage preflight check failed:\n{error}\nClick 'Recheck Storage' to retry."
        )
        self.status_bar.showMessage("Storage check failed")
        self._update_start_button()

    def _on_storage_result(self, preflight: dict) -> None:
        storage = preflight.get("storage", {})
        available = storage.get("available", False)
        status = preflight.get("status", "UNKNOWN")

        total_bytes = self.manager.storage_info.total_bytes if (self.manager.storage_info and available) else 0
        used_bytes = self.manager.storage_info.used_bytes if (self.manager.storage_info and available) else 0
        req_bytes = preflight.get("total_required_bytes", 0)
        safety_bytes = preflight.get("safety_margin_bytes", 0)
        free_bytes = preflight.get("free_bytes", 0)

        if available:
            self.storage_total_label.setText(format_bytes(total_bytes))
            self.storage_used_label.setText(format_bytes(used_bytes))
            self.storage_free_label.setText(format_bytes(free_bytes))
            self.preflight_view.quota_bar.set_storage_data(
                total_bytes=total_bytes,
                used_bytes=used_bytes,
                required_bytes=req_bytes,
                buffer_bytes=safety_bytes,
                is_insufficient=(status == "INSUFFICIENT"),
            )
        else:
            self.storage_total_label.setText("—")
            self.storage_used_label.setText("—")
            self.storage_free_label.setText("—")
            self.preflight_view.quota_bar.set_storage_data(0, 0, 0, 0)

        mode_label = preflight.get("quality_mode", "original").replace("_", " ").title()
        self.storage_required_label.setText(
            f"{format_bytes(req_bytes)} ({mode_label}, incl. {format_bytes(safety_bytes)} buffer)"
            if req_bytes > 0 else "0 bytes"
        )

        if status == "ENOUGH":
            self.storage_status_label.setText(
                f"✅ Capacity Confirmed: Sufficient space ({format_bytes(free_bytes)} free for {format_bytes(req_bytes)} payload)"
            )
            warns = preflight.get("warnings", [])
            self.warnings_label.setText("\n".join(warns) if warns else "")
            self.status_bar.showMessage("Storage verified: Capacity sufficient")
        elif status == "INSUFFICIENT":
            shortfall = preflight.get("shortfall_bytes", 0)
            self.storage_status_label.setText(
                f"❌ Insufficient Storage: Shortfall of {format_bytes(shortfall)}"
            )
            recs = "\n".join(f"• {r}" for r in preflight.get("recommendations", []))
            self.warnings_label.setText(
                f"❌ DESTINATION STORAGE INSUFFICIENT!\n\n"
                f"Required Payload : {format_bytes(req_bytes)} (includes {format_bytes(safety_bytes)} buffer)\n"
                f"Available Space  : {format_bytes(free_bytes)}\n"
                f"Missing Space    : {format_bytes(shortfall)}\n\n"
                f"Practical Options:\n{recs}"
            )
            self.status_bar.showMessage(f"Storage check: Need {format_bytes(shortfall)} more space")
        else:
            error_msg = storage.get("error") or "Could not determine destination storage quota"
            self.storage_status_label.setText(f"⚠️ Capacity Unknown: {error_msg}")
            recs = "\n".join(f"• {r}" for r in preflight.get("recommendations", []))
            self.warnings_label.setText(
                f"⚠️ STORAGE CAPACITY UNKNOWN:\n{error_msg}\n\n"
                f"Recommendations:\n{recs}"
            )
            self.status_bar.showMessage("Storage check: capacity unknown")

        self._update_start_button()

    def _on_quality_mode_changed(self, mode: UploadQualityMode) -> None:
        mode_title = mode.value.replace("_", " ").title()
        self.status_bar.showMessage(f"Upload quality mode set to: {mode_title}")
        if self._is_connected:
            self._check_storage()
        elif self.manager.scan_result or self.manager.media_repo.total_count() > 0:
            preflight = self.manager.preflight_check(quality_mode=mode)
            self._on_storage_result(preflight)
        self._update_start_button()

    # ------------------------------------------------------------------
    # Migration Execution & State
    # ------------------------------------------------------------------

    def _update_start_button(self) -> None:
        """Enable start button only when archives are scanned, connected, and capacity confirmed."""
        total = self.manager.media_repo.total_count() or (
            self.manager.scan_result.total_media_count if self.manager.scan_result else 0
        )
        has_items = total > 0
        can_proceed = (
            self.manager.last_preflight is not None
            and self.manager.last_preflight.can_proceed
        )
        enabled = bool(self._is_connected and has_items and can_proceed)
        self.start_btn.setEnabled(enabled)

        # Update ReviewView summary
        mode = self.quality_selector.get_selected_mode()
        total_size = self.manager.media_repo.total_media_size()
        preflight_est = (
            self.manager.last_preflight.estimated_upload_bytes
            if self.manager.last_preflight and self.manager.last_preflight.estimated_upload_bytes
            else total_size
        )
        counts = self.manager.get_status_counts()
        self.review_view.update_summary(
            sources_count=len(self._archive_paths),
            sources_size_str=format_bytes(total_size),
            account_email=self.oauth.user_email,
            quality_mode_str=mode.value.replace("_", " ").title(),
            estimated_payload_str=format_bytes(preflight_est),
            photos_count=int(self.stat_photos._val.text() or "0"),
            videos_count=int(self.stat_videos._val.text() or "0"),
            duplicates_count=counts.get("SKIPPED", 0),
            preflight_confirmed=bool(can_proceed),
            can_proceed=enabled,
        )

    def _start_migration(self) -> None:
        """Confirm and initiate background upload process."""
        if not self._is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect your Google account first.")
            return

        total = self.manager.media_repo.total_count()
        if total == 0:
            QMessageBox.information(self, "No Files", "No media files found. Scan archives first.")
            return

        mode = self.quality_selector.get_selected_mode()
        mode_title = mode.value.replace("_", " ").title()
        total_size = self.manager.media_repo.total_media_size()
        preflight_est = (
            self.manager.last_preflight.estimated_upload_bytes
            if self.manager.last_preflight and self.manager.last_preflight.estimated_upload_bytes
            else total_size
        )

        reply = QMessageBox.question(
            self,
            "Confirm Migration",
            f"Ready to migrate {total} files?\n\n"
            f"• Upload Quality Mode : {mode_title}\n"
            f"• Original Media Size : {format_bytes(total_size)}\n"
            f"• Estimated Payload   : {format_bytes(preflight_est)}\n\n"
            f"Uploads count against your Google storage quota.\n"
            f"Source files are never modified.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Switch to Active Migration Tab
        self.tabs.setCurrentIndex(5)

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.migration_log.clear()
        self.migration_log.append(f"Starting migration in {mode_title} mode...")
        self._update_timer.start()

        def get_token():
            creds = self.oauth.get_credentials()
            return creds.token if creds else ""

        worker = ProgressWorker(
            self.manager.start_migration,
            access_token_provider=get_token,
            recreate_albums=self.config.recreate_albums,
            quality_mode=mode,
        )
        worker.signals.progress.connect(self._on_upload_progress)
        worker.signals.finished.connect(self._on_migration_finished)
        worker.signals.error.connect(self._on_migration_error)
        self.thread_pool.start(worker)

    def _on_upload_progress(self, completed: int, total: int, current_file: str) -> None:
        percent = int(completed / total * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.current_file_label.setText(f"📄 {current_file}")
        self.migration_log.append(f"[{completed}/{total}] {current_file}")

    @Slot()
    def _refresh_stats(self) -> None:
        """Periodic refresh of progress metrics."""
        try:
            counts = self.manager.get_status_counts()
            uploaded = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0)
            failed = counts.get("FAILED_PERMANENT", 0) + counts.get("FAILED_RETRYABLE", 0)
            pending = counts.get("DISCOVERED", 0) + counts.get("READY", 0) + counts.get("UPLOADING", 0)
            skipped = counts.get("SKIPPED", 0)
            needs_review = counts.get("NEEDS_REVIEW", 0)
            total = self.manager.media_repo.total_count()

            self.stat_uploaded._val.setText(str(uploaded))
            self.stat_failed._val.setText(str(failed))
            self.stat_pending._val.setText(str(pending))
            self.stat_skipped._val.setText(str(skipped))
            self.stat_review._val.setText(str(needs_review))

            self.review_btn.setText(f"⚠️ Review Ambiguous ({needs_review})")
            self.review_btn.setEnabled(needs_review > 0)

            done = uploaded + skipped + failed + needs_review
            percent = int(done / total * 100) if total > 0 else 0
            self.progress_bar.setValue(percent)

            self.phase_label.setText(f"Phase: {self.manager.phase.value}")

            speed = self.manager.transfer_speed
            if speed > 0:
                self.speed_label.setText(f"📶 {format_bytes(int(speed))}/s")
                eta = self.manager.eta_seconds
                if eta > 0:
                    mins = int(eta // 60)
                    secs = int(eta % 60)
                    self.eta_label.setText(f"⏱ ~{mins}m {secs}s remaining")
        except Exception:
            pass

    def _on_migration_finished(self) -> None:
        self._update_timer.stop()
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.retry_btn.setEnabled(True)
        self.view_report_btn.setEnabled(True)
        self._refresh_stats()
        self.inventory_view.reload_data()
        self.history_view.reload_data()

        counts = self.manager.get_status_counts()
        uploaded = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0)
        failed = counts.get("FAILED_PERMANENT", 0) + counts.get("FAILED_RETRYABLE", 0)

        if self.manager.is_cancelled:
            self.migration_log.append("\n⏹️ Migration cancelled by user.")
            self.status_bar.showMessage("Migration cancelled")
        elif failed > 0:
            self.migration_log.append(
                f"\n⚠️ Migration completed with {failed} failures. {uploaded} uploaded."
            )
            self.status_bar.showMessage(f"Migration completed: {uploaded} uploaded, {failed} failed")
        else:
            self.migration_log.append(f"\n✅ Migration complete! {uploaded} files uploaded.")
            self.status_bar.showMessage(f"Migration complete: {uploaded} files uploaded")

    def _on_migration_error(self, error: str) -> None:
        self._update_timer.stop()
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.migration_log.append(f"\n❌ Migration error: {error}")
        self.status_bar.showMessage("Migration failed")

    def _toggle_pause(self) -> None:
        if self.manager.is_paused:
            self.manager.resume()
            self.pause_btn.setText("⏸️ Pause")
            self.status_bar.showMessage("Resumed")
        else:
            self.manager.pause()
            self.pause_btn.setText("▶️ Resume")
            self.status_bar.showMessage("Paused")

    def _cancel_migration(self) -> None:
        reply = QMessageBox.question(
            self,
            "Cancel Migration",
            "Cancel the migration? Progress is saved and can be resumed later.",
        )
        if reply == QMessageBox.Yes:
            self.manager.cancel()

    def _retry_failed(self) -> None:
        from photoport.storage.models import MediaItemStatus
        retryable = self.manager.media_repo.get_by_status(MediaItemStatus.FAILED_RETRYABLE)
        for item in retryable:
            if item.id and item.retry_count < self.config.max_retries:
                self.manager.media_repo.update_status(item.id, MediaItemStatus.READY)
        self.migration_log.append(f"🔄 Reset {len(retryable)} items for retry")
        self._update_start_button()

    def _review_ambiguous_items(self) -> None:
        """Open reconciliation dialog for items in NEEDS_REVIEW status."""
        from photoport.storage.models import MediaItemStatus
        items = self.manager.media_repo.get_by_status(MediaItemStatus.NEEDS_REVIEW, limit=500)
        if not items:
            QMessageBox.information(
                self, "No Items", "There are currently no items in NEEDS_REVIEW status."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Review Ambiguous Uploads ({len(items)} items)")
        dialog.resize(850, 500)
        d_layout = QVBoxLayout(dialog)

        info_banner = QLabel(
            "<b>⚠️ Google Photos API Ambiguity Reconciliation:</b><br>"
            "These media files experienced timeouts or ambiguous responses during creation.<br>"
            "Because Google Photos API does not permit querying items by hash, "
            "automatic retry is prohibited to prevent duplicate uploads.<br><br>"
            "Please check your Google Photos library to confirm whether these items appear, "
            "then choose an action below:"
        )
        info_banner.setWordWrap(True)
        info_banner.setStyleSheet(
            "color: #fde68a; background-color: rgba(245, 158, 11, 0.15); border: 1px solid #d97706; padding: 10px; border-radius: 6px;"
        )
        d_layout.addWidget(info_banner)

        table = QTableWidget(len(items), 3)
        table.setHorizontalHeaderLabels(["File Name", "ZIP Path", "Detail / Error"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for row, it in enumerate(items):
            table.setItem(row, 0, QTableWidgetItem(it.file_name))
            table.setItem(row, 1, QTableWidgetItem(it.zip_member_path))
            table.setItem(row, 2, QTableWidgetItem(it.error_message or "Ambiguous creation outcome"))
        d_layout.addWidget(table)

        btn_layout = QHBoxLayout()

        def apply_reconciliation(action: str):
            selected_rows = [index.row() for index in table.selectionModel().selectedRows()]
            target_items = [items[r] for r in selected_rows] if selected_rows else items
            count = 0
            for it in target_items:
                if it.id and self.manager.reconcile_item(it.id, action):
                    count += 1
            self.migration_log.append(f"Reconciled {count} items with action '{action}'")
            self._refresh_stats()
            self.inventory_view.reload_data()
            dialog.accept()

        mark_btn = QPushButton("✅ Mark as Uploaded (Found in Photos)")
        mark_btn.clicked.connect(lambda: apply_reconciliation("mark_uploaded"))
        btn_layout.addWidget(mark_btn)

        retry_btn = QPushButton("🔄 Force Re-upload (Confirmed Missing)")
        retry_btn.clicked.connect(lambda: apply_reconciliation("force_retry"))
        btn_layout.addWidget(retry_btn)

        skip_btn = QPushButton("⏭️ Skip Files")
        skip_btn.clicked.connect(lambda: apply_reconciliation("skip"))
        btn_layout.addWidget(skip_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(close_btn)

        d_layout.addLayout(btn_layout)
        dialog.exec()

    # ------------------------------------------------------------------
    # Reports & Exports
    # ------------------------------------------------------------------

    def _view_report(self) -> None:
        report_gen = ReportGenerator(self.manager.db)
        report_text = report_gen.get_readable_report()
        self.migration_log.setPlainText(report_text)

    def _view_historical_report(self, session: object) -> None:
        report_gen = ReportGenerator(self.manager.db)
        report_text = report_gen.get_readable_report(session)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Migration Report — Session #{session.id}")
        dialog.resize(750, 500)
        lay = QVBoxLayout(dialog)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(report_text)
        lay.addWidget(te)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        lay.addWidget(close_btn)
        dialog.exec()

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON Report", "migration_report.json", "JSON (*.json)"
        )
        if path:
            report_gen = ReportGenerator(self.manager.db)
            report_gen.export_json(Path(path))
            self.status_bar.showMessage(f"JSON report saved to {path}")

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV Report", "migration_report.csv", "CSV (*.csv)"
        )
        if path:
            report_gen = ReportGenerator(self.manager.db)
            report_gen.export_csv(Path(path))
            self.status_bar.showMessage(f"CSV report saved to {path}")

    # ------------------------------------------------------------------
    # Theme & Settings Actions
    # ------------------------------------------------------------------

    def _on_theme_changed(self, mode: str) -> None:
        self._current_theme = mode
        self.setStyleSheet(generate_stylesheet(mode))
        self.status_bar.showMessage(f"Theme switched to {mode.title()} mode")

    def _clear_cache(self) -> None:
        import shutil
        if self.config.temp_dir.exists():
            for child in self.config.temp_dir.iterdir():
                try:
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                except Exception:
                    pass
        QMessageBox.information(self, "Cache Cleared", "Temporary cache directory cleaned.")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {__app_name__}",
            f"{__app_name__} v{__version__}\n\n"
            "Google Photos Takeout Migration Tool\n\n"
            "Migrates media from Google Takeout archives\n"
            "into your personal Google Photos library.\n\n"
            "• Original quality and Storage Saver modes\n"
            "• Quota preflight check with safety buffers\n"
            "• Deduplication & album recreation\n"
            "• Interrupt recovery & audit reports",
        )

    def closeEvent(self, event) -> None:
        """Clean up on window close."""
        self._update_timer.stop()
        self.manager.close()
        super().closeEvent(event)


class _QtLogHandler(logging.Handler):
    """Logging handler that writes to a QTextEdit widget."""

    def __init__(self, text_edit: QTextEdit) -> None:
        super().__init__()
        self.text_edit = text_edit
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            QTimer.singleShot(0, lambda: self.text_edit.append(msg))
        except Exception:
            pass
