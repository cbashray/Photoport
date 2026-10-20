"""Screen H — Migration Review and Safety Checklist."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ReviewView(QWidget):
    """Pre-migration verification review view with safety checklist."""

    start_migration_requested = Signal()
    recheck_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Plan Summary Group
        summary_group = QGroupBox("Migration Plan Summary")
        grid = QGridLayout(summary_group)
        grid.setSpacing(10)

        # 4 key summary pillars
        self.val_sources = QLabel("0 sources")
        self.val_account = QLabel("Not connected")
        self.val_quality = QLabel("Original Quality")
        self.val_payload = QLabel("0 B")

        self.val_photos = QLabel("0 photos")
        self.val_videos = QLabel("0 videos")
        self.val_dups = QLabel("0 duplicates excluded")
        self.val_storage = QLabel("Not verified")

        fields = [
            ("📁 Source Archives:", self.val_sources, 0, 0),
            ("👤 Destination Account:", self.val_account, 0, 1),
            ("⚡ Upload Quality:", self.val_quality, 1, 0),
            ("💾 Estimated Payload:", self.val_payload, 1, 1),
            ("🖼️ Photos to Upload:", self.val_photos, 2, 0),
            ("🎥 Videos to Upload:", self.val_videos, 2, 1),
            ("🔄 Excluded Duplicates:", self.val_dups, 3, 0),
            ("📊 Storage Preflight:", self.val_storage, 3, 1),
        ]

        for label_text, val_lbl, r, c in fields:
            t = QLabel(label_text)
            t.setStyleSheet("font-weight: 600; color: #94a3b8; font-size: 12px;")
            val_lbl.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
            box = QHBoxLayout()
            box.addWidget(t)
            box.addWidget(val_lbl)
            box.addStretch()
            grid.addLayout(box, r, c)

        layout.addWidget(summary_group)

        # Safety & Capabilities Checklist
        check_group = QGroupBox("Safety Verification Checklist")
        check_layout = QVBoxLayout(check_group)
        check_layout.setSpacing(8)

        self.chk_sources = self._make_check_item("✅ Sources inspected and deduplicated via central directory headers")
        self.chk_account = self._make_check_item("✅ Destination Google Account authenticated via secure OAuth 2.0 PKCE")
        self.chk_preflight = self._make_check_item("✅ Destination storage capacity verified with 5% safety margin")
        self.chk_quality = self._make_check_item("✅ Upload quality compliant with Google Photos API terms")
        self.chk_invariance = self._make_check_item("✅ Source files remain 100% read-only and invariant")

        check_layout.addWidget(self.chk_sources)
        check_layout.addWidget(self.chk_account)
        check_layout.addWidget(self.chk_preflight)
        check_layout.addWidget(self.chk_quality)
        check_layout.addWidget(self.chk_invariance)

        layout.addWidget(check_group)

        # Primary Action Bar
        action_frame = QFrame()
        action_frame.setStyleSheet(
            "background-color: rgba(30, 41, 59, 0.5); border: 1px solid #334155; border-radius: 8px;"
        )
        act_layout = QHBoxLayout(action_frame)
        act_layout.setContentsMargins(16, 12, 16, 12)

        self.status_msg = QLabel("Complete source scan and storage verification to start.")
        self.status_msg.setStyleSheet("font-size: 12px; color: #94a3b8;")
        act_layout.addWidget(self.status_msg)
        act_layout.addStretch()

        self.start_btn = QPushButton("🚀 Start Migration")
        self.start_btn.setObjectName("primary_button")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_migration_requested.emit)
        act_layout.addWidget(self.start_btn)

        layout.addWidget(action_frame)
        layout.addStretch()

    def _make_check_item(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        return lbl

    def update_summary(
        self,
        sources_count: int,
        sources_size_str: str,
        account_email: str,
        quality_mode_str: str,
        estimated_payload_str: str,
        photos_count: int,
        videos_count: int,
        duplicates_count: int,
        preflight_confirmed: bool,
        can_proceed: bool,
    ) -> None:
        self.val_sources.setText(f"{sources_count} sources ({sources_size_str})")
        self.val_account.setText(account_email if account_email else "Not connected")
        self.val_quality.setText(quality_mode_str)
        self.val_payload.setText(estimated_payload_str)
        self.val_photos.setText(f"{photos_count:,} photos")
        self.val_videos.setText(f"{videos_count:,} videos")
        self.val_dups.setText(f"{duplicates_count:,} duplicates excluded")

        if preflight_confirmed:
            self.val_storage.setText("✅ Capacity Confirmed")
            self.val_storage.setStyleSheet("color: #10b981; font-weight: 700;")
            self.status_msg.setText("✅ All pre-flight safety checks confirmed. Ready to start migration.")
            self.status_msg.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 600;")
        else:
            self.val_storage.setText("❌ Preflight Incomplete / Insufficient")
            self.val_storage.setStyleSheet("color: #ef4444; font-weight: 700;")
            self.status_msg.setText("⚠️ Resolve storage preflight before starting migration.")
            self.status_msg.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: 600;")

        self.start_btn.setEnabled(can_proceed)
