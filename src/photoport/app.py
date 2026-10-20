"""PhotoPort application entry point."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Launch the PhotoPort desktop application."""
    # Ensure the src directory is in the path
    src_dir = Path(__file__).parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from photoport.ui.main_window import MainWindow

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PhotoPort")
    app.setOrganizationName("PhotoPort")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
