
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "hospital.db"

with sqlite3.connect(DB_PATH) as conn:
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT,
            created_at TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            department TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK (is_active IN (0,1))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS doctor_slots (
            slot_id TEXT PRIMARY KEY,
            doctor_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            FOREIGN KEY (doctor_id)
                REFERENCES doctors(doctor_id),
            CHECK (ends_at > starts_at),
            UNIQUE (doctor_id, starts_at)
        )
    """)

    conn.commit()

print("Patient and doctor tables created successfully.")
