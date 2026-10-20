"""Drag-and-drop file and folder landing zone."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class DropZoneWidget(QFrame):
    """Interactive drag and drop zone for selecting Takeout ZIPs and folders."""

    files_dropped = Signal(list)  # list[str] paths
    browse_files_requested = Signal()
    browse_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("drop_zone")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel("📥")
        self.icon_label.setStyleSheet("font-size: 36px;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)

        self.headline = QLabel("Drag & Drop Google Takeout ZIPs or Folders Here")
        self.headline.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        self.headline.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.headline)

        self.subtext = QLabel(
            "Supports multi-part Takeout archives (.zip) or previously extracted photo folders"
        )
        self.subtext.setStyleSheet("font-size: 12px; color: #94a3b8;")
        self.subtext.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtext)

        # Buttons
        from PySide6.QtWidgets import QHBoxLayout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.setAlignment(Qt.AlignCenter)

        self.btn_zip = QPushButton("Browse ZIP Archives...")
        self.btn_zip.setObjectName("primary_button")
        self.btn_zip.clicked.connect(self.browse_files_requested.emit)
        btn_layout.addWidget(self.btn_zip)

        self.btn_folder = QPushButton("Browse Extracted Folder...")
        self.btn_folder.setObjectName("secondary_button")
        self.btn_folder.clicked.connect(self.browse_folder_requested.emit)
        btn_layout.addWidget(self.btn_folder)

        layout.addLayout(btn_layout)

        self._set_default_style()

    def _set_default_style(self) -> None:
        self.setStyleSheet(
            "#drop_zone {"
            "  border: 2px dashed #475569;"
            "  border-radius: 10px;"
            "  background-color: rgba(30, 41, 59, 0.4);"
            "}"
            "#drop_zone:hover {"
            "  border-color: #38bdf8;"
            "  background-color: rgba(30, 41, 59, 0.7);"
            "}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(
                "#drop_zone {"
                "  border: 2px dashed #38bdf8;"
                "  border-radius: 10px;"
                "  background-color: rgba(56, 189, 248, 0.1);"
                "}"
            )
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_default_style()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_default_style()
        urls = event.mimeData().urls()
        paths: list[str] = []
        for url in urls:
            path_str = url.toLocalFile()
            if path_str:
                p = Path(path_str)
                if p.is_file() and p.suffix.lower() == ".zip":
                    paths.append(str(p))
                elif p.is_dir():
                    # check if folder has zips or media
                    zips = list(p.glob("*.zip"))
                    if zips:
                        paths.extend(str(z) for z in zips)
                    else:
                        paths.append(str(p))
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
