"""Main application window — PhotoPort desktop interface."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
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
from photoport.config import get_config
from photoport.migration.migration_manager import MigrationManager
from photoport.migration.report_generator import ReportGenerator
from photoport.ui.workers import ProgressWorker, Worker
from photoport.utils.disk_space import format_bytes
from photoport.utils.logging_config import setup_logging

logger = logging.getLogger("photoport.ui.main_window")

STYLE_SHEET = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #2d2d44;
    border-radius: 8px;
    background-color: #16213e;
    padding: 8px;
}
QTabBar::tab {
    background-color: #1a1a2e;
    color: #8888aa;
    padding: 10px 24px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    min-width: 120px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background-color: #16213e;
    color: #00d2ff;
    border-bottom: 2px solid #00d2ff;
}
QTabBar::tab:hover {
    color: #ffffff;
}
QPushButton {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #1a5276;
    border-radius: 6px;
    padding: 10px 20px;
    font-weight: 600;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #1a5276;
    border-color: #00d2ff;
}
QPushButton:pressed {
    background-color: #0a2647;
}
QPushButton:disabled {
    background-color: #1a1a2e;
    color: #555;
    border-color: #333;
}
QPushButton#primary_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d2ff, stop:1 #3a7bd5);
    color: #ffffff;
    border: none;
    font-size: 14px;
    padding: 12px 28px;
}
QPushButton#primary_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00e5ff, stop:1 #4a8be5);
}
QPushButton#danger_button {
    background-color: #c0392b;
    border-color: #e74c3c;
}
QPushButton#danger_button:hover {
    background-color: #e74c3c;
}
QGroupBox {
    font-weight: 700;
    font-size: 14px;
    color: #00d2ff;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    background-color: rgba(22, 33, 62, 0.5);
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
}
QProgressBar {
    border: 1px solid #2d2d44;
    border-radius: 6px;
    text-align: center;
    height: 24px;
    background-color: #1a1a2e;
    color: #ffffff;
    font-weight: 600;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d2ff, stop:1 #3a7bd5);
    border-radius: 5px;
}
QTextEdit {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #2d2d44;
    border-radius: 6px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    padding: 8px;
}
QLabel#stat_value {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#stat_label {
    font-size: 11px;
    color: #8888aa;
    font-weight: 400;
}
QLabel#header_label {
    font-size: 28px;
    font-weight: 800;
    color: #ffffff;
}
QLabel#sub_label {
    font-size: 13px;
    color: #8888aa;
}
QLabel#warning_label {
    color: #f39c12;
    font-weight: 600;
}
QLabel#success_label {
    color: #2ecc71;
    font-weight: 600;
}
QLabel#error_label {
    color: #e74c3c;
    font-weight: 600;
}
QStatusBar {
    background-color: #0d1117;
    color: #8888aa;
    border-top: 1px solid #2d2d44;
}
QMenuBar {
    background-color: #0d1117;
    color: #e0e0e0;
}
QMenuBar::item:selected {
    background-color: #1a5276;
}
QMenu {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #2d2d44;
}
QMenu::item:selected {
    background-color: #1a5276;
}
"""


class MainWindow(QMainWindow):
    """PhotoPort main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.config = get_config()
        self.logger = setup_logging(self.config.log_dir, self.config.log_level)

        # Core services
        self.oauth = GoogleOAuth(self.config.credentials_path, self.config.token_path)
        self.manager = MigrationManager(self.config)
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)

        # State
        self._archive_paths: list[str] = []
        self._is_connected = False

        # Build UI
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(1100, 750)
        self.resize(1280, 850)
        self.setStyleSheet(STYLE_SHEET)

        self._build_menu_bar()
        self._build_ui()
        self._build_status_bar()

        # Timer for periodic UI updates during migration
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh_stats)
        self._update_timer.setInterval(2000)

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

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction("About", self._show_about)

    # ------------------------------------------------------------------
    # Main UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 8, 16, 8)
        main_layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"⚡ {__app_name__}")
        title.setObjectName("header_label")
        header.addWidget(title)
        header.addStretch()

        self.account_label = QLabel("Not connected")
        self.account_label.setObjectName("sub_label")
        header.addWidget(self.account_label)

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

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dashboard_tab(), "📊 Dashboard")
        self.tabs.addTab(self._build_archives_tab(), "📁 Archives")
        self.tabs.addTab(self._build_migration_tab(), "🚀 Migration")
        self.tabs.addTab(self._build_log_tab(), "📋 Log")
        main_layout.addWidget(self.tabs)

    # ------------------------------------------------------------------
    # Dashboard Tab
    # ------------------------------------------------------------------

    def _build_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # Stats grid
        stats_group = QGroupBox("Migration Overview")
        stats_layout = QHBoxLayout()

        self.stat_archives = self._create_stat_widget("0", "Archives")
        self.stat_total = self._create_stat_widget("0", "Total Files")
        self.stat_photos = self._create_stat_widget("0", "Photos")
        self.stat_videos = self._create_stat_widget("0", "Videos")
        self.stat_uploaded = self._create_stat_widget("0", "Uploaded")
        self.stat_failed = self._create_stat_widget("0", "Failed")
        self.stat_skipped = self._create_stat_widget("0", "Skipped")
        self.stat_pending = self._create_stat_widget("0", "Pending")
        self.stat_review = self._create_stat_widget("0", "Needs Review")

        for w in (
            self.stat_archives, self.stat_total, self.stat_photos, self.stat_videos,
            self.stat_uploaded, self.stat_failed, self.stat_skipped, self.stat_pending,
            self.stat_review,
        ):
            stats_layout.addWidget(w)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        info_row = QHBoxLayout()
        self.phase_label = QLabel("Phase: Idle")
        self.phase_label.setObjectName("sub_label")
        info_row.addWidget(self.phase_label)

        self.current_file_label = QLabel("")
        self.current_file_label.setObjectName("sub_label")
        info_row.addWidget(self.current_file_label)

        info_row.addStretch()

        self.speed_label = QLabel("")
        self.speed_label.setObjectName("sub_label")
        info_row.addWidget(self.speed_label)

        self.eta_label = QLabel("")
        self.eta_label.setObjectName("sub_label")
        info_row.addWidget(self.eta_label)

        progress_layout.addLayout(info_row)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # Storage section
        storage_group = QGroupBox("Destination Storage & Capacity Preflight")
        storage_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        self.storage_total_label = QLabel("—")
        self.storage_used_label = QLabel("—")
        self.storage_free_label = QLabel("—")
        self.storage_required_label = QLabel("—")

        row1.addWidget(QLabel("Total:"))
        row1.addWidget(self.storage_total_label)
        row1.addWidget(QLabel("Used:"))
        row1.addWidget(self.storage_used_label)
        row1.addWidget(QLabel("Free:"))
        row1.addWidget(self.storage_free_label)
        row1.addWidget(QLabel("Required:"))
        row1.addWidget(self.storage_required_label)
        row1.addStretch()

        self.retry_storage_btn = QPushButton("🔄 Recheck Storage")
        self.retry_storage_btn.setObjectName("secondary_button")
        self.retry_storage_btn.clicked.connect(self._check_storage)
        row1.addWidget(self.retry_storage_btn)
        storage_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.storage_status_label = QLabel("Capacity status: Not checked")
        self.storage_status_label.setObjectName("sub_label")
        row2.addWidget(self.storage_status_label)
        row2.addStretch()
        storage_layout.addLayout(row2)

        storage_group.setLayout(storage_layout)
        layout.addWidget(storage_group)

        # Warnings
        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("warning_label")
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        layout.addStretch()
        return tab

    def _create_stat_widget(self, value: str, label: str) -> QWidget:
        """Create a stat display widget with value + label."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(2)

        val_label = QLabel(value)
        val_label.setObjectName("stat_value")
        val_label.setAlignment(Qt.AlignCenter)

        desc_label = QLabel(label)
        desc_label.setObjectName("stat_label")
        desc_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(val_label)
        layout.addWidget(desc_label)

        w._val = val_label  # Store reference for updates
        return w

    # ------------------------------------------------------------------
    # Archives Tab
    # ------------------------------------------------------------------

    def _build_archives_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Controls
        btn_row = QHBoxLayout()

        open_btn = QPushButton("📂 Open ZIP Files")
        open_btn.clicked.connect(self._open_archives)
        btn_row.addWidget(open_btn)

        folder_btn = QPushButton("📁 Open Folder")
        folder_btn.clicked.connect(self._open_archive_folder)
        btn_row.addWidget(folder_btn)

        scan_btn = QPushButton("🔍 Scan Archives")
        scan_btn.setObjectName("primary_button")
        scan_btn.clicked.connect(self._scan_archives)
        self.scan_btn = scan_btn
        btn_row.addWidget(scan_btn)

        btn_row.addStretch()

        self.archive_size_label = QLabel("")
        self.archive_size_label.setObjectName("sub_label")
        btn_row.addWidget(self.archive_size_label)

        layout.addLayout(btn_row)

        # Archive list display
        self.archive_list = QTextEdit()
        self.archive_list.setReadOnly(True)
        self.archive_list.setMaximumHeight(150)
        self.archive_list.setPlaceholderText(
            "No archives selected. Click 'Open ZIP Files' or 'Open Folder' to add archives."
        )
        layout.addWidget(self.archive_list)

        # Scan results
        self.scan_results = QTextEdit()
        self.scan_results.setReadOnly(True)
        self.scan_results.setPlaceholderText("Scan results will appear here after scanning.")
        layout.addWidget(self.scan_results)

        return tab

    # ------------------------------------------------------------------
    # Migration Tab
    # ------------------------------------------------------------------

    def _build_migration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Controls
        ctrl_row = QHBoxLayout()

        self.start_btn = QPushButton("▶️ Start Migration")
        self.start_btn.setObjectName("primary_button")
        self.start_btn.clicked.connect(self._start_migration)
        self.start_btn.setEnabled(False)
        ctrl_row.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸️ Pause")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.setEnabled(False)
        ctrl_row.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("⏹️ Cancel")
        self.cancel_btn.setObjectName("danger_button")
        self.cancel_btn.clicked.connect(self._cancel_migration)
        self.cancel_btn.setEnabled(False)
        ctrl_row.addWidget(self.cancel_btn)

        ctrl_row.addStretch()

        self.review_btn = QPushButton("⚠️ Review Ambiguous (0)")
        self.review_btn.clicked.connect(self._review_ambiguous_items)
        self.review_btn.setEnabled(False)
        ctrl_row.addWidget(self.review_btn)

        self.retry_btn = QPushButton("🔄 Retry Failed")
        self.retry_btn.clicked.connect(self._retry_failed)
        self.retry_btn.setEnabled(False)
        ctrl_row.addWidget(self.retry_btn)

        layout.addLayout(ctrl_row)

        # Migration progress display
        self.migration_log = QTextEdit()
        self.migration_log.setReadOnly(True)
        self.migration_log.setPlaceholderText(
            "Migration progress will appear here.\n\n"
            "Steps:\n"
            "1. Add archives in the Archives tab\n"
            "2. Scan the archives\n"
            "3. Connect your Google account\n"
            "4. Click 'Start Migration'"
        )
        layout.addWidget(self.migration_log)

        # Report buttons
        report_row = QHBoxLayout()
        report_row.addStretch()

        self.view_report_btn = QPushButton("📊 View Report")
        self.view_report_btn.clicked.connect(self._view_report)
        self.view_report_btn.setEnabled(False)
        report_row.addWidget(self.view_report_btn)

        layout.addLayout(report_row)

        return tab

    # ------------------------------------------------------------------
    # Log Tab
    # ------------------------------------------------------------------

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("Application logs will appear here.")

        layout.addWidget(self.log_display)

        # Add a log handler that writes to the QTextEdit
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
    # Actions
    # ------------------------------------------------------------------

    def _check_auth_state(self) -> None:
        """Check initial authentication state."""
        if self.oauth.is_authenticated:
            self._is_connected = True
            email = self.oauth.user_email
            self.account_label.setText(f"✅ {email}" if email else "✅ Connected")
            self.connect_btn.setText("Disconnect")
            self.switch_btn.setVisible(True)
            self.status_bar.showMessage(
                f"Connected to {email}" if email else "Connected to Google account"
            )
            self._check_storage()
        else:
            self._is_connected = False
            self.account_label.setText("⚪ Not connected")
            self.connect_btn.setText("Connect Account")
            self.switch_btn.setVisible(False)

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
        """Safely switch Google account."""
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
        self.account_label.setText(f"✅ {email}" if email else "✅ Connected")
        self.connect_btn.setText("Disconnect")
        self.switch_btn.setVisible(True)
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
            self.connect_btn.setText("Connect Account")
            self.switch_btn.setVisible(False)
            self.storage_total_label.setText("-")
            self.storage_used_label.setText("-")
            self.storage_free_label.setText("-")
            self.storage_status_label.setText("")
            self.status_bar.showMessage("Disconnected")
            self._update_start_button()

    def _open_archives(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Takeout ZIP Archives", "", "ZIP Archives (*.zip)"
        )
        if files:
            self._archive_paths.extend(files)
            self._archive_paths = list(set(self._archive_paths))  # deduplicate
            self._update_archive_display()

    def _open_archive_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with Archives or Extracted Media"
        )
        if folder:
            from pathlib import Path
            p = Path(folder)
            zips = list(p.glob("*.zip"))
            if zips:
                self._archive_paths.extend(str(z) for z in zips)
            else:
                self._archive_paths.append(str(p))
            self._archive_paths = list(set(self._archive_paths))
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
        self.archive_list.setPlainText("\n".join(self._archive_paths))
        self.archive_size_label.setText(
            f"{len(self._archive_paths)} source(s) • {format_bytes(total_size)}"
        )
        self.stat_archives._val.setText(str(len(self._archive_paths)))
        self._update_start_button()

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
        scan = result  # ArchiveScanResult

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

        # Update dashboard stats
        counts = self.manager.media_repo.count_by_status()
        total = self.manager.media_repo.total_count()
        self.stat_total._val.setText(str(total))
        self.stat_pending._val.setText(
            str(counts.get("DISCOVERED", 0) + counts.get("READY", 0))
        )
        self.stat_skipped._val.setText(str(counts.get("SKIPPED", 0)))

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

    def _start_migration(self) -> None:
        """Start the migration process."""
        if not self._is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect your Google account first.")
            return

        total = self.manager.media_repo.total_count()
        if total == 0:
            QMessageBox.information(self, "No Files", "No media files found. Scan archives first.")
            return

        # Preflight confirmation
        total_size = self.manager.media_repo.total_media_size()
        reply = QMessageBox.question(
            self,
            "Confirm Migration",
            f"Ready to migrate {total} files ({format_bytes(total_size)})?\n\n"
            f"This will upload media to your Google Photos library.\n"
            f"Uploads count against your Google storage quota.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Update UI
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.migration_log.clear()
        self._update_timer.start()

        # Start migration in background
        def get_token():
            creds = self.oauth.get_credentials()
            return creds.token if creds else ""

        worker = ProgressWorker(
            self.manager.start_migration,
            access_token_provider=get_token,
            recreate_albums=self.config.recreate_albums,
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
        """Periodic refresh of dashboard statistics."""
        try:
            counts = self.manager.get_status_counts()
            uploaded = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0)
            failed = counts.get("FAILED_PERMANENT", 0) + counts.get("FAILED_RETRYABLE", 0)
            pending = counts.get("DISCOVERED", 0) + counts.get("READY", 0) + counts.get("UPLOADING", 0)
            skipped = counts.get("SKIPPED", 0)
            total = self.manager.media_repo.total_count()

            self.stat_uploaded._val.setText(str(uploaded))
            self.stat_failed._val.setText(str(failed))
            self.stat_pending._val.setText(str(pending))
            self.stat_skipped._val.setText(str(skipped))
            needs_review = counts.get("NEEDS_REVIEW", 0)
            self.stat_review._val.setText(str(needs_review))
            self.review_btn.setText(f"⚠️ Review Ambiguous ({needs_review})")
            self.review_btn.setEnabled(needs_review > 0)

            # Progress
            done = uploaded + skipped + failed + needs_review
            percent = int(done / total * 100) if total > 0 else 0
            self.progress_bar.setValue(percent)

            # Phase
            self.phase_label.setText(f"Phase: {self.manager.phase.value}")

            # Speed / ETA
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
        """Reset retryable failures to READY state."""
        retryable = self.manager.media_repo.get_by_status(
            __import__("photoport.storage.models", fromlist=["MediaItemStatus"]).MediaItemStatus.FAILED_RETRYABLE
        )
        from photoport.storage.models import MediaItemStatus
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

        # Warning explanation banner
        info_banner = QLabel(
            "<b>⚠️ Google Photos API Ambiguity Explanation:</b><br>"
            "These media files experienced timeouts or ambiguous responses during creation.<br>"
            "Because Google Photos API does not permit querying items by file content or hash, "
            "automatic retry is prohibited to prevent duplicate uploads.<br><br>"
            "Please check your Google Photos library to confirm whether these items appear, "
            "then choose an action below:"
        )
        info_banner.setWordWrap(True)
        info_banner.setStyleSheet("color: #ffcc00; background-color: #2a2a3e; padding: 10px; border-radius: 6px;")
        d_layout.addWidget(info_banner)

        # Table of items
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

        # Actions
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

    def _check_storage(self) -> None:
        if not self._is_connected:
            self.storage_status_label.setText("Connect your Google account to verify destination storage.")
            return

        self.status_bar.showMessage("Running storage preflight check...")

        def check():
            token = self.oauth.access_token
            if not token:
                raise ValueError("No access token available")
            return self.manager.preflight_check(token)

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

        if available:
            self.storage_total_label.setText(format_bytes(self.manager.storage_info.total_bytes))
            self.storage_used_label.setText(format_bytes(self.manager.storage_info.used_bytes))
            self.storage_free_label.setText(format_bytes(preflight.get("free_bytes", 0)))
        else:
            self.storage_total_label.setText("—")
            self.storage_used_label.setText("—")
            self.storage_free_label.setText("—")

        req_bytes = preflight.get("total_required_bytes", 0)
        safety_bytes = preflight.get("safety_margin_bytes", 0)
        self.storage_required_label.setText(
            f"{format_bytes(req_bytes)} (incl. {format_bytes(safety_bytes)} buffer)" if req_bytes > 0 else "0 bytes"
        )

        if status == "ENOUGH":
            self.storage_status_label.setText(
                f"✅ Capacity Confirmed: Sufficient space ({format_bytes(preflight.get('free_bytes', 0))} free for {format_bytes(req_bytes)} payload)"
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
                f"Available Space  : {format_bytes(preflight.get('free_bytes', 0))}\n"
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

    def _view_report(self) -> None:
        report_gen = ReportGenerator(self.manager.db)
        report_text = report_gen.get_readable_report()
        self.migration_log.setPlainText(report_text)

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

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {__app_name__}",
            f"{__app_name__} v{__version__}\n\n"
            "Google Photos Takeout Migration Tool\n\n"
            "Migrates media from Google Takeout ZIP archives\n"
            "into your personal Google Photos library.\n\n"
            "• Original quality preservation\n"
            "• Album recreation\n"
            "• Resume from interruptions\n"
            "• Duplicate detection\n"
            "• Migration reports",
        )

    def _update_start_button(self) -> None:
        """Enable start button only when archives are scanned, connected, and capacity is confirmed."""
        total = self.manager.media_repo.total_count() or (
            self.manager.scan_result.total_media_count if self.manager.scan_result else 0
        )
        has_items = total > 0
        can_proceed = (
            self.manager.last_preflight is not None
            and self.manager.last_preflight.can_proceed
        )
        self.start_btn.setEnabled(self._is_connected and has_items and can_proceed)

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
            # Use QTimer to ensure thread safety
            QTimer.singleShot(0, lambda: self.text_edit.append(msg))
        except Exception:
            pass
