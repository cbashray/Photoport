"""Screen N — Application Settings and Configuration View."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from photoport import __app_name__, __version__

if TYPE_CHECKING:
    from photoport.config import AppConfig


class SettingsView(QWidget):
    """Configuration settings view for PhotoPort."""

    theme_changed = Signal(str)  # "dark" or "light"
    clear_cache_requested = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Visual Theme
        theme_box = QGroupBox("Appearance & Display")
        t_layout = QHBoxLayout(theme_box)
        t_layout.addWidget(QLabel("Interface Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark (Slate Navy)", "Light (Clean)"])
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        t_layout.addWidget(self.theme_combo)
        t_layout.addStretch()
        layout.addWidget(theme_box)

        # Storage & Migration Policy
        policy_box = QGroupBox("Storage Preflight & Safety Policy")
        p_layout = QVBoxLayout(policy_box)
        p_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Storage Safety Buffer Margin (%):"))
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 50.0)
        margin_val = getattr(self.config, "storage_safety_margin_percent", 5.0)
        self.spin_margin.setValue(margin_val)
        self.spin_margin.setSuffix("%")
        self.spin_margin.valueChanged.connect(self._on_margin_changed)
        row1.addWidget(self.spin_margin)
        row1.addStretch()
        p_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Max Automatic Retries per Item:"))
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(1, 10)
        self.spin_retries.setValue(getattr(self.config, "max_retries", 5))
        self.spin_retries.valueChanged.connect(self._on_retries_changed)
        row2.addWidget(self.spin_retries)
        row2.addStretch()
        p_layout.addLayout(row2)

        layout.addWidget(policy_box)

        # Storage & Cache Info
        cache_box = QGroupBox("Local Ledger & Temporary Cache")
        c_layout = QVBoxLayout(cache_box)
        c_layout.setSpacing(10)

        info_row = QHBoxLayout()
        self.db_path_lbl = QLabel(f"SQLite Ledger: {self.config.db_path}")
        self.db_path_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        info_row.addWidget(self.db_path_lbl)
        info_row.addStretch()

        self.btn_cleanup = QPushButton("🧹 Clean Temp Cache")
        self.btn_cleanup.setObjectName("secondary_button")
        self.btn_cleanup.clicked.connect(self.clear_cache_requested.emit)
        info_row.addWidget(self.btn_cleanup)
        c_layout.addLayout(info_row)

        layout.addWidget(cache_box)

        # About & Privacy
        about_box = QGroupBox("About & Privacy")
        a_layout = QVBoxLayout(about_box)
        a_layout.setSpacing(6)

        about_title = QLabel(f"{__app_name__} Desktop v{__version__}")
        about_title.setStyleSheet("font-weight: 700; font-size: 14px; color: #f8fafc;")
        a_layout.addWidget(about_title)

        about_desc = QLabel(
            "PhotoPort is an open-source, local-first utility. Your media files, EXIF tags, "
            "and OAuth credentials never leave your personal computer except when communicating directly "
            "with official Google API endpoints. Source files are strictly accessed in read-only mode."
        )
        about_desc.setWordWrap(True)
        about_desc.setStyleSheet("font-size: 12px; color: #94a3b8;")
        a_layout.addWidget(about_desc)

        layout.addWidget(about_box)
        layout.addStretch()

    def _on_theme_changed(self, idx: int) -> None:
        mode = "dark" if idx == 0 else "light"
        self.theme_changed.emit(mode)

    def _on_margin_changed(self, val: float) -> None:
        self.config.storage_safety_margin_percent = val

    def _on_retries_changed(self, val: int) -> None:
        self.config.max_retries = val
