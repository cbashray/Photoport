"""Visual proportional quota bar showing destination storage breakdown."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from photoport.utils.disk_space import format_bytes


class _ProportionalQuotaBar(QWidget):
    """Custom paint widget rendering a segmented storage bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self.total_bytes: int = 0
        self.used_bytes: int = 0
        self.required_bytes: int = 0
        self.buffer_bytes: int = 0
        self.is_insufficient: bool = False

    def update_metrics(
        self,
        total: int,
        used: int,
        required: int,
        buffer: int,
        is_insufficient: bool = False,
    ) -> None:
        self.total_bytes = max(0, total)
        self.used_bytes = max(0, used)
        self.required_bytes = max(0, required)
        self.buffer_bytes = max(0, buffer)
        self.is_insufficient = is_insufficient
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        w = rect.width()
        h = rect.height()

        # Background (Free space)
        painter.setBrush(QColor("#1e293b"))
        painter.setPen(QColor("#334155"))
        painter.drawRoundedRect(rect, 4, 4)

        if self.total_bytes <= 0:
            return

        # Calculate proportional widths
        used_ratio = min(1.0, self.used_bytes / self.total_bytes)
        req_ratio = min(1.0 - used_ratio, self.required_bytes / self.total_bytes)
        buf_ratio = min(1.0 - used_ratio - req_ratio, self.buffer_bytes / self.total_bytes)

        x = 0
        used_w = int(w * used_ratio)
        if used_w > 0:
            painter.setBrush(QColor("#64748b"))  # Slate (Current Used)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 0, used_w, h, 4, 4)
            x += used_w

        req_w = int(w * req_ratio)
        if req_w > 0:
            color = QColor("#ef4444") if self.is_insufficient else QColor("#2563eb")
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(x, 0, req_w, h)
            x += req_w

        buf_w = int(w * buf_ratio)
        if buf_w > 0:
            painter.setBrush(QColor("#f59e0b"))  # Amber buffer
            painter.setPen(Qt.NoPen)
            painter.drawRect(x, 0, buf_w, h)


class QuotaBarWidget(QFrame):
    """Storage capacity widget featuring a proportional bar and detail metrics."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("quota_bar_container")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Header summary
        header_row = QHBoxLayout()
        self.title_label = QLabel("Destination Google One / Photos Storage")
        self.title_label.setStyleSheet("font-weight: 700; font-size: 13px;")
        header_row.addWidget(self.title_label)
        header_row.addStretch()

        self.summary_label = QLabel("Not checked")
        self.summary_label.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        header_row.addWidget(self.summary_label)
        layout.addLayout(header_row)

        # Visual bar
        self.bar = _ProportionalQuotaBar(self)
        layout.addWidget(self.bar)

        # Legend / Breakdown
        legend_row = QHBoxLayout()
        legend_row.setSpacing(16)

        self.lbl_used = self._make_legend_item("■ In Use", "#64748b", "—")
        self.lbl_req = self._make_legend_item("■ Required", "#2563eb", "—")
        self.lbl_buf = self._make_legend_item("■ Safety Buffer", "#f59e0b", "—")
        self.lbl_free = self._make_legend_item("■ Free Remaining", "#10b981", "—")

        legend_row.addWidget(self.lbl_used)
        legend_row.addWidget(self.lbl_req)
        legend_row.addWidget(self.lbl_buf)
        legend_row.addWidget(self.lbl_free)
        legend_row.addStretch()

        layout.addLayout(legend_row)

    def _make_legend_item(self, title: str, color: str, initial_val: str) -> QLabel:
        lbl = QLabel(f"<span style='color:{color}; font-weight:bold;'>{title}:</span> {initial_val}")
        lbl.setStyleSheet("font-size: 11px;")
        lbl._title = title
        lbl._color = color
        return lbl

    def set_storage_data(
        self,
        total_bytes: int,
        used_bytes: int,
        required_bytes: int = 0,
        buffer_bytes: int = 0,
        is_insufficient: bool = False,
    ) -> None:
        """Update storage numbers and redraw proportional bar."""
        free_bytes = max(0, total_bytes - used_bytes - required_bytes)

        self.bar.update_metrics(
            total=total_bytes,
            used=used_bytes,
            required=required_bytes,
            buffer=buffer_bytes,
            is_insufficient=is_insufficient,
        )

        if total_bytes > 0:
            used_pct = (used_bytes / total_bytes) * 100
            self.summary_label.setText(
                f"{format_bytes(used_bytes)} of {format_bytes(total_bytes)} used ({used_pct:.1f}%)"
            )
            self.lbl_used.setText(
                f"<span style='color:{self.lbl_used._color}; font-weight:bold;'>{self.lbl_used._title}:</span> {format_bytes(used_bytes)}"
            )
            self.lbl_req.setText(
                f"<span style='color:{self.lbl_req._color}; font-weight:bold;'>{self.lbl_req._title}:</span> {format_bytes(required_bytes)}"
            )
            self.lbl_buf.setText(
                f"<span style='color:{self.lbl_buf._color}; font-weight:bold;'>{self.lbl_buf._title}:</span> {format_bytes(buffer_bytes)}"
            )
            self.lbl_free.setText(
                f"<span style='color:{self.lbl_free._color}; font-weight:bold;'>{self.lbl_free._title}:</span> {format_bytes(free_bytes)}"
            )
        else:
            self.summary_label.setText("Storage not checked")
            self.lbl_used.setText(f"<span style='color:{self.lbl_used._color}; font-weight:bold;'>{self.lbl_used._title}:</span> —")
            self.lbl_req.setText(f"<span style='color:{self.lbl_req._color}; font-weight:bold;'>{self.lbl_req._title}:</span> —")
            self.lbl_buf.setText(f"<span style='color:{self.lbl_buf._color}; font-weight:bold;'>{self.lbl_buf._title}:</span> —")
            self.lbl_free.setText(f"<span style='color:{self.lbl_free._color}; font-weight:bold;'>{self.lbl_free._title}:</span> —")
