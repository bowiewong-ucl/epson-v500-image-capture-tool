"""Starts the GUI."""

from __future__ import annotations

import sys
from pathlib import Path

ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.png"


def run_gui() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .. import APP_NAME, config
    from .main_window import MainWindow

    if sys.platform == "win32":
        # Show our icon in the taskbar rather than Python's when run from source.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("V500Capture")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON)))
    window = MainWindow(config.load())
    window.show()
    return app.exec()
