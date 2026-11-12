import os
import sqlite3
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

DB_PATH = Path(
    os.getenv(
        "HOSPITAL_DB_PATH",
        str(BACKEND_DIR / "hospital.db"),
    )
).expanduser().resolve()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn
