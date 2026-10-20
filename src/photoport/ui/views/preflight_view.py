"""Screens D & E — Google Account Connection and Storage Capacity Preflight."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from photoport.ui.components.quota_bar import QuotaBarWidget


class PreflightView(QWidget):
    """View managing Google account connection and destination quota verification."""

    connect_account_requested = Signal()
    switch_account_requested = Signal()
    recheck_storage_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Account Connection Card (Screen D)
        account_box = QGroupBox("Destination Google Account")
        acc_layout = QHBoxLayout(account_box)
        acc_layout.setContentsMargins(14, 14, 14, 14)

        # Avatar placeholder
        self.avatar_label = QLabel("👤")
        self.avatar_label.setStyleSheet(
            "font-size: 24px; background-color: #334155; border-radius: 18px; padding: 6px;"
        )
        acc_layout.addWidget(self.avatar_label)

        # Account Info
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.account_label = QLabel("Not connected")
        self.account_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        info_col.addWidget(self.account_label)

        self.account_subtext = QLabel(
            "OAuth 2.0 PKCE • Scopes: Photos (appendonly, appcreateddata) & Drive Quota (readonly)"
        )
        self.account_subtext.setStyleSheet("font-size: 11px; color: #94a3b8;")
        info_col.addWidget(self.account_subtext)
        acc_layout.addLayout(info_col, stretch=1)

        # Action Buttons
        self.connect_btn = QPushButton("Connect Account")
        self.connect_btn.setObjectName("primary_button")
        self.connect_btn.clicked.connect(self.connect_account_requested.emit)
        acc_layout.addWidget(self.connect_btn)

        self.switch_btn = QPushButton("Switch Account")
        self.switch_btn.setObjectName("secondary_button")
        self.switch_btn.clicked.connect(self.switch_account_requested.emit)
        self.switch_btn.setVisible(False)
        acc_layout.addWidget(self.switch_btn)

        layout.addWidget(account_box)

        # Storage Preflight Section (Screen E)
        storage_box = QGroupBox("Destination Storage Capacity & Preflight Check")
        storage_layout = QVBoxLayout(storage_box)
        storage_layout.setSpacing(12)

        # Quota Bar visual
        self.quota_bar = QuotaBarWidget()
        storage_layout.addWidget(self.quota_bar)

        # Numeric Metrics Row
        metrics_frame = QFrame()
        metrics_frame.setStyleSheet(
            "background-color: rgba(15, 23, 42, 0.5); border: 1px solid #334155; border-radius: 6px;"
        )
        metrics_row = QHBoxLayout(metrics_frame)
        metrics_row.setContentsMargins(12, 10, 12, 10)

        self.storage_total_label = QLabel("—")
        self.storage_used_label = QLabel("—")
        self.storage_free_label = QLabel("—")
        self.storage_required_label = QLabel("—")

        for title, lbl in [
            ("Total Quota:", self.storage_total_label),
            ("In Use:", self.storage_used_label),
            ("Available Free:", self.storage_free_label),
            ("Required Payload:", self.storage_required_label),
        ]:
            lbl.setStyleSheet("font-weight: 700; color: #f8fafc;")
            col = QVBoxLayout()
            col.setSpacing(2)
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet("font-size: 10px; color: #94a3b8; font-weight: 600; text-transform: uppercase;")
            col.addWidget(t_lbl)
            col.addWidget(lbl)
            metrics_row.addLayout(col)

        metrics_row.addStretch()

        self.retry_storage_btn = QPushButton("🔄 Recheck Storage")
        self.retry_storage_btn.setObjectName("secondary_button")
        self.retry_storage_btn.clicked.connect(self.recheck_storage_requested.emit)
        metrics_row.addWidget(self.retry_storage_btn)

        storage_layout.addWidget(metrics_frame)

        # Capacity Status Label
        self.storage_status_label = QLabel("Capacity status: Not checked")
        self.storage_status_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #94a3b8;")
        storage_layout.addWidget(self.storage_status_label)

        # Warnings / Recommendations Box
        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("warning_label")
        self.warnings_label.setWordWrap(True)
        storage_layout.addWidget(self.warnings_label)

        layout.addWidget(storage_box)
        layout.addStretch()
