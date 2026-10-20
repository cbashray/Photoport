"""Screen M — Migration Sessions History View."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from photoport.storage.models import MigrationSession
from photoport.ui.components.status_badge import StatusBadge

if TYPE_CHECKING:
    from photoport.storage.repository import SessionRepository


class HistoryView(QWidget):
    """View presenting past migration sessions and outcomes."""

    view_report_requested = Signal(object)  # MigrationSession

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_repo: SessionRepository | None = None
        self._sessions: list[MigrationSession] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header bar
        bar = QFrame()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Migration Sessions Ledger")
        lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        bar_layout.addWidget(lbl)
        bar_layout.addStretch()

        self.btn_refresh = QPushButton("🔄 Refresh History")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self.reload_data)
        bar_layout.addWidget(self.btn_refresh)

        layout.addWidget(bar)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Session ID", "Started", "Destination Account", "Quality Mode", "Status", "Uploaded / Total", "Actions"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def set_repository(self, repo: SessionRepository) -> None:
        self._session_repo = repo
        self.reload_data()

    def reload_data(self) -> None:
        if not self._session_repo:
            return

        self._sessions = self._session_repo.get_all(limit=50)
        self.table.setRowCount(len(self._sessions))

        for row, sess in enumerate(self._sessions):
            self.table.setItem(row, 0, QTableWidgetItem(f"#{sess.id}"))
            date_str = str(sess.started_at)[:19] if sess.started_at else "—"
            self.table.setItem(row, 1, QTableWidgetItem(date_str))
            self.table.setItem(row, 2, QTableWidgetItem(sess.destination_account or "—"))

            q_mode = sess.quality_mode.value if hasattr(sess.quality_mode, 'value') else str(sess.quality_mode)
            self.table.setItem(row, 3, QTableWidgetItem(q_mode.replace("_", " ").title()))

            status_str = sess.status.value if hasattr(sess.status, 'value') else str(sess.status)
            badge = StatusBadge(status_str)
            self.table.setCellWidget(row, 4, badge)

            counts_str = f"{sess.total_uploaded} / {sess.total_files_discovered}"
            self.table.setItem(row, 5, QTableWidgetItem(counts_str))

            btn = QPushButton("View Report")
            btn.setObjectName("secondary_button")
            btn.clicked.connect(lambda _, s=sess: self.view_report_requested.emit(s))
            self.table.setCellWidget(row, 6, btn)
