"""Screen A — Application Overview & Workflow Landing View."""

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

from photoport.ui.components.stat_card import StatCard


class StepBadge(QFrame):
    """Visual step indicator card."""

    def __init__(self, step_num: int, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.num_lbl = QLabel(f"Step {step_num}")
        self.num_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #38bdf8; text-transform: uppercase;")
        layout.addWidget(self.num_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(self.title_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.sub_lbl.setWordWrap(True)
        layout.addWidget(self.sub_lbl)

        self.setStyleSheet(
            "StepBadge { background-color: rgba(30, 41, 59, 0.6); border: 1px solid #334155; border-radius: 6px; }"
        )


class OverviewView(QWidget):
    """Overview & landing screen presenting migration status and guided steps."""

    navigate_requested = Signal(int)  # tab index
    start_migration_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Welcome Hero Banner
        hero = QFrame()
        hero.setObjectName("hero_frame")
        hero.setStyleSheet(
            "#hero_frame {"
            "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e293b, stop:1 #0f172a);"
            "  border: 1px solid #334155;"
            "  border-radius: 8px;"
            "  padding: 16px;"
            "}"
        )
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 12, 16, 12)

        left_hero = QVBoxLayout()
        title = QLabel("Safe Google Photos Library Migration")
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        left_hero.addWidget(title)

        subtitle = QLabel(
            "Inspect Google Takeout archives, verify destination storage quota with safety margins, "
            "select compliant upload quality, and migrate with bit-for-bit confidence."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 12px; color: #94a3b8; margin-top: 4px;")
        left_hero.addWidget(subtitle)
        hero_layout.addLayout(left_hero, stretch=3)

        hero_btn_col = QVBoxLayout()
        self.hero_action_btn = QPushButton("📂 Select Sources")
        self.hero_action_btn.setObjectName("primary_button")
        self.hero_action_btn.clicked.connect(lambda: self.navigate_requested.emit(1))
        hero_btn_col.addWidget(self.hero_action_btn)
        hero_layout.addLayout(hero_btn_col, stretch=1)

        layout.addWidget(hero)

        # Stepper Row
        stepper_box = QGroupBox("Migration Journey")
        stepper_layout = QHBoxLayout(stepper_box)
        stepper_layout.setSpacing(8)

        self.step1 = StepBadge(1, "Select Sources", "Add ZIPs or folders")
        self.step2 = StepBadge(2, "Scan & Inventory", "Deduplicate & inspect")
        self.step3 = StepBadge(3, "Connect Account", "OAuth 2.0 PKCE auth")
        self.step4 = StepBadge(4, "Storage Preflight", "Quota & safety buffer")
        self.step5 = StepBadge(5, "Upload Quality", "Original or Saver")
        self.step6 = StepBadge(6, "Review & Migrate", "Safe verification")

        for s in (self.step1, self.step2, self.step3, self.step4, self.step5, self.step6):
            stepper_layout.addWidget(s)

        layout.addWidget(stepper_box)

        # Stats Grid
        stats_group = QGroupBox("Library & Session Overview")
        stats_grid = QGridLayout(stats_group)
        stats_grid.setSpacing(8)

        self.stat_archives = StatCard("0", "Archives", "📦")
        self.stat_total = StatCard("0", "Discovered", "📑")
        self.stat_photos = StatCard("0", "Photos", "🖼️")
        self.stat_videos = StatCard("0", "Videos", "🎥")
        self.stat_uploaded = StatCard("0", "Uploaded", "✅")
        self.stat_pending = StatCard("0", "Pending", "⏳")
        self.stat_failed = StatCard("0", "Failed", "❌")
        self.stat_skipped = StatCard("0", "Skipped", "⏭️")
        self.stat_review = StatCard("0", "Needs Review", "⚠️")

        cards = [
            (self.stat_archives, 0, 0),
            (self.stat_total, 0, 1),
            (self.stat_photos, 0, 2),
            (self.stat_videos, 0, 3),
            (self.stat_uploaded, 0, 4),
            (self.stat_pending, 1, 0),
            (self.stat_failed, 1, 1),
            (self.stat_skipped, 1, 2),
            (self.stat_review, 1, 3),
        ]
        for w, r, c in cards:
            stats_grid.addWidget(w, r, c)

        layout.addWidget(stats_group)
        layout.addStretch()
