from __future__ import annotations

import sqlite3
from pathlib import Path

from src.db.schema import create_schema

DEFAULT_DB_PATH = Path("data/processed/nutrition.db")


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_database(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    path = Path(db_path)
    with get_connection(path) as conn:
        create_schema(conn)
    return path

