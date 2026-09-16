"""应用装配与启动。"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .database import Database
from .paths import default_db_path
from .ui.main_window import MainWindow

APPLICATION_NAME = "设备持有成本跟踪"


def main(argv: list[str] | None = None) -> int:
    # QApplication 必须先于任何 widget 创建，且全局只能有一个
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APPLICATION_NAME)

    database = Database(default_db_path())
    window = MainWindow(database)
    window.show()

    try:
        return app.exec()
    finally:
        database.close()
