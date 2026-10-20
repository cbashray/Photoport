"""Colored semantic status badge for items and migration states."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

STATUS_STYLES = {
    "READY": ("#2563eb", "rgba(37, 99, 235, 0.15)", "#93c5fd"),
    "UPLOADED": ("#059669", "rgba(16, 185, 129, 0.15)", "#6ee7b7"),
    "VERIFIED": ("#059669", "rgba(16, 185, 129, 0.15)", "#6ee7b7"),
    "FAILED_PERMANENT": ("#dc2626", "rgba(239, 68, 68, 0.15)", "#fca5a5"),
    "FAILED_RETRYABLE": ("#d97706", "rgba(245, 158, 11, 0.15)", "#fcd34d"),
    "NEEDS_REVIEW": ("#d97706", "rgba(245, 158, 11, 0.2)", "#fbbf24"),
    "SKIPPED": ("#64748b", "rgba(100, 116, 139, 0.15)", "#cbd5e1"),
    "DISCOVERED": ("#0284c7", "rgba(14, 165, 233, 0.15)", "#7dd3fc"),
    "COMPLETED": ("#059669", "rgba(16, 185, 129, 0.15)", "#6ee7b7"),
    "IN_PROGRESS": ("#2563eb", "rgba(37, 99, 235, 0.15)", "#93c5fd"),
    "CANCELLED": ("#64748b", "rgba(100, 116, 139, 0.15)", "#cbd5e1"),
    "FAILED": ("#dc2626", "rgba(239, 68, 68, 0.15)", "#fca5a5"),
}


class StatusBadge(QLabel):
    """Badge widget rendering colored pill label for a given state string."""

    def __init__(self, status: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        status_key = status.upper().replace(" ", "_")
        border, bg, text_col = STATUS_STYLES.get(
            status_key, ("#64748b", "rgba(100, 116, 139, 0.15)", "#cbd5e1")
        )
        display_text = status.replace("_", " ").title()
        self.setText(f" {display_text} ")
        self.setStyleSheet(
            f"background-color: {bg};"
            f"border: 1px solid {border};"
            f"color: {text_col};"
            f"border-radius: 4px;"
            f"font-size: 11px;"
            f"font-weight: 600;"
            f"padding: 2px 6px;"
        )
