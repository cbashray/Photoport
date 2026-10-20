"""Stat card component displaying a key metric and descriptive label."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class StatCard(QFrame):
    """Metric display card with value and label.

    Includes backward-compatible `_val` attribute for existing test assertions.
    """

    def __init__(
        self,
        value: str | int = "0",
        label: str = "",
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("stat_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        self._val = QLabel(str(value))
        self._val.setObjectName("stat_value")
        self._val.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._val)

        self._desc = QLabel(label)
        self._desc.setObjectName("stat_label")
        self._desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._desc)

        self.setStyleSheet(
            "#stat_card {"
            "  background-color: rgba(30, 41, 59, 0.7);"
            "  border: 1px solid #334155;"
            "  border-radius: 8px;"
            "  min-width: 80px;"
            "}"
            "#stat_card:hover {"
            "  border-color: #475569;"
            "  background-color: rgba(30, 41, 59, 0.95);"
            "}"
        )

    def set_value(self, value: str | int) -> None:
        """Update displayed metric value."""
        self._val.setText(str(value))

    def value(self) -> str:
        """Get displayed metric value text."""
        return self._val.text()

    def set_label(self, label: str) -> None:
        """Update metric description label."""
        self._desc.setText(label)
