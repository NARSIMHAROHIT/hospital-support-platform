
import os
import sqlite3
from pathlib import Path

db_path = os.getenv("HOSPITAL_DB_PATH")
if not db_path:
    raise SystemExit(
        "HOSPITAL_DB_PATH must be set before running migrations."
    )

DB_PATH = Path(db_path).expanduser().resolve()

with sqlite3.connect(DB_PATH) as conn:
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            patient_id TEXT UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK (role IN ('patient', 'doctor', 'admin')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id)
                REFERENCES users(user_id)
        )
    """)

    conn.commit()

print("Authentication tables created successfully.")
