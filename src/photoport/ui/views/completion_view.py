"""Screen K — Migration Completion Report View."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CompletionView(QWidget):
    """Completion summary view for full and partial migration runs."""

    export_json_requested = Signal()
    export_csv_requested = Signal()
    view_inventory_requested = Signal()
    return_overview_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Status Header Card
        self.header_card = QFrame()
        self.header_card.setObjectName("completion_header")
        h_layout = QVBoxLayout(self.header_card)
        h_layout.setContentsMargins(16, 14, 16, 14)
        h_layout.setSpacing(4)

        self.title_lbl = QLabel("✅ Migration Completed")
        self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #10b981;")
        h_layout.addWidget(self.title_lbl)

        self.subtitle_lbl = QLabel("All eligible media files were processed.")
        self.subtitle_lbl.setStyleSheet("font-size: 13px; color: #94a3b8;")
        h_layout.addWidget(self.subtitle_lbl)

        layout.addWidget(self.header_card)

        # Metrics Breakdown
        metrics_box = QGroupBox("Migration Outcome Metrics")
        grid = QGridLayout(metrics_box)
        grid.setSpacing(10)

        self.stat_uploaded = QLabel("0")
        self.stat_failed = QLabel("0")
        self.stat_skipped = QLabel("0")
        self.stat_review = QLabel("0")
        self.stat_bytes = QLabel("0 B")
        self.stat_duration = QLabel("—")

        items = [
            ("✅ Uploaded & Verified:", self.stat_uploaded, "#10b981", 0, 0),
            ("❌ Failed Items:", self.stat_failed, "#ef4444", 0, 1),
            ("⏭️ Skipped / Unsupported:", self.stat_skipped, "#94a3b8", 1, 0),
            ("⚠️ Needs Review:", self.stat_review, "#f59e0b", 1, 1),
            ("💾 Total Bytes Uploaded:", self.stat_bytes, "#38bdf8", 2, 0),
            ("⏱ Duration / Time:", self.stat_duration, "#cbd5e1", 2, 1),
        ]

        for title, lbl, color, r, c in items:
            t = QLabel(title)
            t.setStyleSheet("font-size: 12px; color: #94a3b8; font-weight: 600;")
            lbl.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {color};")
            row = QHBoxLayout()
            row.addWidget(t)
            row.addWidget(lbl)
            row.addStretch()
            grid.addLayout(row, r, c)

        layout.addWidget(metrics_box)

        # Full Report Text Area
        report_box = QGroupBox("Detailed Audit Report")
        rep_layout = QVBoxLayout(report_box)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setPlaceholderText("Detailed report will be populated upon migration completion.")
        rep_layout.addWidget(self.report_text)
        layout.addWidget(report_box)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_json = QPushButton("📄 Export JSON Report")
        self.btn_json.clicked.connect(self.export_json_requested.emit)
        btn_row.addWidget(self.btn_json)

        self.btn_csv = QPushButton("📊 Export CSV Report")
        self.btn_csv.clicked.connect(self.export_csv_requested.emit)
        btn_row.addWidget(self.btn_csv)

        self.btn_inventory = QPushButton("🔍 Inspect File Inventory")
        self.btn_inventory.clicked.connect(self.view_inventory_requested.emit)
        btn_row.addWidget(self.btn_inventory)

        btn_row.addStretch()

        self.btn_overview = QPushButton("🏠 Return to Overview")
        self.btn_overview.setObjectName("primary_button")
        self.btn_overview.clicked.connect(self.return_overview_requested.emit)
        btn_row.addWidget(self.btn_overview)

        layout.addLayout(btn_row)

    def set_results(
        self,
        uploaded: int,
        failed: int,
        skipped: int,
        review: int,
        bytes_str: str,
        duration_str: str,
        report_body: str,
        was_cancelled: bool = False,
    ) -> None:
        self.stat_uploaded.setText(f"{uploaded:,}")
        self.stat_failed.setText(f"{failed:,}")
        self.stat_skipped.setText(f"{skipped:,}")
        self.stat_review.setText(f"{review:,}")
        self.stat_bytes.setText(bytes_str)
        self.stat_duration.setText(duration_str)
        self.report_text.setPlainText(report_body)

        if was_cancelled:
            self.title_lbl.setText("⏹️ Migration Cancelled")
            self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #94a3b8;")
            self.subtitle_lbl.setText("Migration was cancelled by user. Completed items are saved.")
        elif failed > 0 or review > 0:
            self.title_lbl.setText("⚠️ Migration Completed with Unresolved Items")
            self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #f59e0b;")
            self.subtitle_lbl.setText(
                f"{uploaded:,} items uploaded. {failed:,} items failed and {review:,} require manual review."
            )
        else:
            self.title_lbl.setText("✅ Migration Successfully Completed!")
            self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #10b981;")
            self.subtitle_lbl.setText("All eligible items were uploaded and verified in your Google Photos library.")
