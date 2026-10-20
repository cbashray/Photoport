"""Screen L — File Inventory and Media Ledger Table View."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from photoport.storage.models import MediaItem, MediaItemStatus
from photoport.ui.components.status_badge import StatusBadge
from photoport.utils.disk_space import format_bytes

if TYPE_CHECKING:
    from photoport.storage.repository import MediaItemRepository


class InventoryView(QWidget):
    """Searchable, filterable file inventory table for discovered media."""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media_repo: MediaItemRepository | None = None
        self._current_items: list[MediaItem] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Filter bar
        filter_box = QFrame()
        filter_box.setStyleSheet(
            "background-color: rgba(30, 41, 59, 0.5); border: 1px solid #334155; border-radius: 6px;"
        )
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(10)

        # Search field
        filter_layout.addWidget(QLabel("🔍 Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by file name or archive path...")
        self.search_input.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.search_input, stretch=2)

        # Status filter
        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            ["All Statuses", "Pending", "Uploaded", "Failed", "Skipped", "Needs Review"]
        )
        self.status_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.status_filter, stretch=1)

        # Refresh
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setObjectName("secondary_button")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        filter_layout.addWidget(self.refresh_btn)

        self.count_label = QLabel("Showing 0 items")
        self.count_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        filter_layout.addWidget(self.count_label)

        layout.addWidget(filter_box)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "File Name", "Type", "Size", "Source Archive / Path", "Metadata", "Status", "Details"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.table)

    def set_repository(self, repo: MediaItemRepository) -> None:
        self._media_repo = repo
        self.reload_data()

    def reload_data(self) -> None:
        if not self._media_repo:
            return

        # Fetch up to 1000 items for responsive display
        status_text = self.status_filter.currentText()
        if status_text == "Pending":
            items = self._media_repo.get_pending_items(limit=1000)
        elif status_text == "Uploaded":
            items = self._media_repo.get_by_status(MediaItemStatus.UPLOADED, limit=1000)
            items.extend(self._media_repo.get_by_status(MediaItemStatus.VERIFIED, limit=1000))
        elif status_text == "Failed":
            items = self._media_repo.get_by_status(MediaItemStatus.FAILED_PERMANENT, limit=1000)
            items.extend(self._media_repo.get_by_status(MediaItemStatus.FAILED_RETRYABLE, limit=1000))
        elif status_text == "Skipped":
            items = self._media_repo.get_by_status(MediaItemStatus.SKIPPED, limit=1000)
        elif status_text == "Needs Review":
            items = self._media_repo.get_by_status(MediaItemStatus.NEEDS_REVIEW, limit=1000)
        else:
            # All items (fetch limit)
            items = self._media_repo.get_all()[:1000]

        query = self.search_input.text().strip().lower()
        if query:
            items = [
                it for it in items
                if query in it.file_name.lower() or query in it.archive_path.lower()
            ]

        self._current_items = items
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._current_items))
        self.count_label.setText(f"Showing {len(self._current_items):,} items")

        for row, it in enumerate(self._current_items):
            self.table.setItem(row, 0, QTableWidgetItem(it.file_name))
            self.table.setItem(row, 1, QTableWidgetItem(it.media_type.value if hasattr(it.media_type, 'value') else str(it.media_type)))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(it.file_size)))
            self.table.setItem(row, 3, QTableWidgetItem(it.archive_path))

            meta_str = "Sidecar+Timestamp" if it.sidecar_path else ("Timestamp" if it.capture_timestamp else "None")
            self.table.setItem(row, 4, QTableWidgetItem(meta_str))

            status_str = it.status.value if hasattr(it.status, 'value') else str(it.status)
            badge = StatusBadge(status_str)
            self.table.setCellWidget(row, 5, badge)

            detail = it.error_message or (f"Google ID: {it.google_media_id}" if it.google_media_id else "")
            self.table.setItem(row, 6, QTableWidgetItem(detail))

    def _on_filter_changed(self) -> None:
        self.reload_data()
