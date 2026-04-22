from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def launch_gui(db_path: str | Path) -> int:
    try:
        from src.gui.app import NutritionDatabaseApp
    except ImportError as exc:
        LOGGER.info("tkinter が利用できないため、ブラウザ GUI に切り替えます: %s", exc)
        from src.gui.web import launch_browser_gui

        return launch_browser_gui(db_path)
    try:
        app = NutritionDatabaseApp(db_path)
        app.mainloop()
        return 0
    except Exception as exc:
        if exc.__class__.__name__ != "TclError":
            raise
        LOGGER.info("tkinter の画面表示が利用できないため、ブラウザ GUI に切り替えます: %s", exc)
        from src.gui.web import launch_browser_gui

        return launch_browser_gui(db_path)
