"""Screens B & C — Source Archive Selection, Drag-and-Drop, and Scan Inventory."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from photoport.ui.components.drop_zone import DropZoneWidget
from photoport.utils.disk_space import format_bytes


class SourcesView(QWidget):
    """View for selecting Takeout ZIPs/folders and displaying scan inventory."""

    open_zips_requested = Signal()
    open_folder_requested = Signal()
    scan_requested = Signal()
    sources_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sources: list[str] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Drop Zone Header
        self.drop_zone = DropZoneWidget()
        self.drop_zone.files_dropped.connect(self.add_sources)
        self.drop_zone.browse_files_requested.connect(self.open_zips_requested.emit)
        self.drop_zone.browse_folder_requested.connect(self.open_folder_requested.emit)
        layout.addWidget(self.drop_zone)

        # Selected Sources Table & Actions
        sources_group = QGroupBox("Configured Source Archives & Folders")
        sources_layout = QVBoxLayout(sources_group)
        sources_layout.setSpacing(8)

        # Action bar
        act_row = QHBoxLayout()
        self.archive_size_label = QLabel("0 source(s) • 0 B")
        self.archive_size_label.setObjectName("sub_label")
        act_row.addWidget(self.archive_size_label)
        act_row.addStretch()

        self.btn_clear = QPushButton("🗑️ Clear Sources")
        self.btn_clear.clicked.connect(self.clear_sources)
        act_row.addWidget(self.btn_clear)

        self.scan_btn = QPushButton("🔍 Scan Archives & Inventory")
        self.scan_btn.setObjectName("primary_button")
        self.scan_btn.clicked.connect(self.scan_requested.emit)
        act_row.addWidget(self.scan_btn)

        sources_layout.addLayout(act_row)

        # Table of source paths
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Source Path", "Type", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setMaximumHeight(130)
        sources_layout.addWidget(self.table)

        # Backward compatibility text edit (hidden or synced)
        self.archive_list = QTextEdit()
        self.archive_list.setReadOnly(True)
        self.archive_list.setMaximumHeight(100)
        self.archive_list.setVisible(False)
        sources_layout.addWidget(self.archive_list)

        layout.addWidget(sources_group)

        # Scan Results & Limitations Box
        results_group = QGroupBox("Scan Inventory & Limitations")
        results_layout = QVBoxLayout(results_group)

        self.scan_results = QTextEdit()
        self.scan_results.setReadOnly(True)
        self.scan_results.setPlaceholderText(
            "Scan results will appear here after scanning archives.\n\n"
            "The scanner calculates:\n"
            "• Eligible photo and video counts\n"
            "• Duplicate Takeout entries (filename + size + CRC32 deduplication)\n"
            "• Sidecar JSON metadata files\n"
            "• Oversized items (>10 GB videos or >200 MB photos)"
        )
        results_layout.addWidget(self.scan_results)
        layout.addWidget(results_group)

    def add_sources(self, paths: list[str]) -> None:
        """Add new source paths, avoiding duplicates."""
        for p in paths:
            if p and p not in self._sources:
                self._sources.append(p)
        self._update_table()
        self.sources_changed.emit(self._sources)

    def clear_sources(self) -> None:
        """Clear all selected sources."""
        self._sources.clear()
        self._update_table()
        self.sources_changed.emit(self._sources)

    def get_sources(self) -> list[str]:
        return list(self._sources)

    def set_sources(self, sources: list[str]) -> None:
        self._sources = list(sources)
        self._update_table()

    def _update_table(self) -> None:
        self.table.setRowCount(len(self._sources))
        total_size = 0
        for row, path_str in enumerate(self._sources):
            p = Path(path_str)
            is_file = p.is_file()
            size = 0
            if is_file:
                with contextlib.suppress(Exception):
                    size = p.stat().st_size
                stype = "ZIP Archive" if p.suffix.lower() == ".zip" else "File"
            else:
                with contextlib.suppress(Exception):
                    for root, _dirs, files in os.walk(path_str):
                        for f in files:
                            with contextlib.suppress(Exception):
                                size += os.path.getsize(os.path.join(root, f))
                stype = "Extracted Folder"

            total_size += size
            self.table.setItem(row, 0, QTableWidgetItem(path_str))
            self.table.setItem(row, 1, QTableWidgetItem(stype))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(size)))

        # Update labels and backward compatibility plain text
        self.archive_size_label.setText(
            f"{len(self._sources)} source(s) • {format_bytes(total_size)}"
        )
        self.archive_list.setPlainText("\n".join(self._sources))
