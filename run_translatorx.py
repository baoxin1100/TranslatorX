from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from translatorx.launcher import hide_pyappify_launcher
from translatorx.logging_setup import install_qt_message_handler, setup_logging
from translatorx.theme import theme_manager
from translatorx.ui import MainWindow
from translatorx.windows import enable_per_monitor_dpi_awareness


def main() -> int:
    setup_logging()
    install_qt_message_handler()
    enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName("TranslatorX")
    app.setApplicationDisplayName("TranslatorX")
    app.setOrganizationName("TranslatorX")
    icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.ico")
    app.setWindowIcon(QIcon(icon_path))
    theme_manager.apply()
    window = MainWindow()
    window.show()
    # Run after Qt has processed the first show event. A launcher remains
    # visible when startup fails, but is hidden once the application is ready.
    QTimer.singleShot(0, hide_pyappify_launcher)
    if os.environ.get("TRANSLATORX_SMOKE_TEST") == "1":
        QTimer.singleShot(2500, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
