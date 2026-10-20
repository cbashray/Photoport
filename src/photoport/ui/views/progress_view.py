"""Screens I & J — Active Migration Progress, Controls, and Error Recovery."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ProgressView(QWidget):
    """View tracking real-time migration progress, throughput, and error recovery."""

    pause_toggled = Signal()
    cancel_requested = Signal()
    retry_requested = Signal()
    review_requested = Signal()
    view_report_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Progress Section
        progress_box = QGroupBox("Migration Execution Status")
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.setSpacing(10)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        # Metrics row: Phase, Current File, Speed, ETA
        info_row = QHBoxLayout()
        self.phase_label = QLabel("Phase: Idle")
        self.phase_label.setStyleSheet("font-weight: 700; color: #38bdf8;")
        info_row.addWidget(self.phase_label)

        self.current_file_label = QLabel("")
        self.current_file_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        info_row.addWidget(self.current_file_label)
        info_row.addStretch()

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("font-weight: 600; color: #10b981;")
        info_row.addWidget(self.speed_label)

        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        info_row.addWidget(self.eta_label)

        progress_layout.addLayout(info_row)
        layout.addWidget(progress_box)

        # Controls & Recovery Action Bar
        ctrl_box = QFrame()
        ctrl_box.setStyleSheet(
            "background-color: rgba(30, 41, 59, 0.4); border: 1px solid #334155; border-radius: 6px;"
        )
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)
        ctrl_layout.setSpacing(10)

        self.pause_btn = QPushButton("⏸️ Pause")
        self.pause_btn.clicked.connect(self.pause_toggled.emit)
        self.pause_btn.setEnabled(False)
        ctrl_layout.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("⏹️ Cancel")
        self.cancel_btn.setObjectName("danger_button")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.cancel_btn.setEnabled(False)
        ctrl_layout.addWidget(self.cancel_btn)

        ctrl_layout.addStretch()

        self.review_btn = QPushButton("⚠️ Review Ambiguous (0)")
        self.review_btn.clicked.connect(self.review_requested.emit)
        self.review_btn.setEnabled(False)
        ctrl_layout.addWidget(self.review_btn)

        self.retry_btn = QPushButton("🔄 Retry Failed")
        self.retry_btn.clicked.connect(self.retry_requested.emit)
        self.retry_btn.setEnabled(False)
        ctrl_layout.addWidget(self.retry_btn)

        self.view_report_btn = QPushButton("📊 View Report")
        self.view_report_btn.clicked.connect(self.view_report_requested.emit)
        self.view_report_btn.setEnabled(False)
        ctrl_layout.addWidget(self.view_report_btn)

        layout.addWidget(ctrl_box)

        # Live Migration Activity Log
        log_box = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_box)

        self.migration_log = QTextEdit()
        self.migration_log.setReadOnly(True)
        self.migration_log.setPlaceholderText(
            "Migration activity and transfer log will appear here during execution."
        )
        log_layout.addWidget(self.migration_log)
        layout.addWidget(log_box)
