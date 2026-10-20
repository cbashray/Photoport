"""Reusable structured resolution banner for errors, warnings, and recovery."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BannerType = Literal["error", "warning", "info", "success"]


class ErrorBanner(QFrame):
    """Structured resolution banner answering:

    1. What happened?
    2. What does it mean for user media?
    3. What should the user do next?
    """

    action_clicked = Signal(str)

    def __init__(
        self,
        banner_type: BannerType = "warning",
        title: str = "",
        what_happened: str = "",
        what_it_means: str = "",
        what_to_do: str = "",
        action_text: str | None = None,
        action_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("resolution_banner")
        self._action_id = action_id

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(6)

        # Header
        self.header_label = QLabel()
        self.header_label.setWordWrap(True)
        self._layout.addWidget(self.header_label)

        # Body
        self.body_label = QLabel()
        self.body_label.setWordWrap(True)
        self._layout.addWidget(self.body_label)

        # Action button row
        self.btn_row = QHBoxLayout()
        self.btn_row.addStretch()
        self.action_btn = QPushButton()
        self.action_btn.clicked.connect(lambda: self.action_clicked.emit(self._action_id))
        self.btn_row.addWidget(self.action_btn)
        self._layout.addLayout(self.btn_row)

        self.set_content(
            banner_type=banner_type,
            title=title,
            what_happened=what_happened,
            what_it_means=what_it_means,
            what_to_do=what_to_do,
            action_text=action_text,
            action_id=action_id,
        )

    def set_content(
        self,
        banner_type: BannerType = "warning",
        title: str = "",
        what_happened: str = "",
        what_it_means: str = "",
        what_to_do: str = "",
        action_text: str | None = None,
        action_id: str = "",
    ) -> None:
        self._action_id = action_id
        theme_map = {
            "error": ("#ef4444", "rgba(239, 68, 68, 0.12)", "#fca5a5", "❌"),
            "warning": ("#f59e0b", "rgba(245, 158, 11, 0.12)", "#fde68a", "⚠️"),
            "info": ("#0ea5e9", "rgba(14, 165, 233, 0.12)", "#bae6fd", "ℹ️"),
            "success": ("#10b981", "rgba(16, 185, 129, 0.12)", "#a7f3d0", "✅"),
        }
        border, bg, text_col, icon = theme_map.get(banner_type, theme_map["warning"])

        self.setStyleSheet(
            f"#resolution_banner {{"
            f"  background-color: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
        )

        self.header_label.setText(f"<b style='color:{border}; font-size:13px;'>{icon} {title}</b>")

        details_html = []
        if what_happened:
            details_html.append(f"<b>What happened:</b> {what_happened}")
        if what_it_means:
            details_html.append(f"<b>Impact on media:</b> {what_it_means}")
        if what_to_do:
            details_html.append(f"<b>Recommended action:</b> {what_to_do}")

        self.body_label.setText("<br>".join(details_html))
        self.body_label.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.4;")

        if action_text:
            self.action_btn.setText(action_text)
            self.action_btn.setVisible(True)
        else:
            self.action_btn.setVisible(False)
