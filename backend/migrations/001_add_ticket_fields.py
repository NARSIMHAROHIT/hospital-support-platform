
import os
import sqlite3
from pathlib import Path

db_path = os.getenv("HOSPITAL_DB_PATH")
if not db_path:
    raise SystemExit(
        "HOSPITAL_DB_PATH must be set before running migrations."
    )

DB_PATH = Path(db_path).expanduser().resolve()

new_columns = {
    "priority": "TEXT NOT NULL DEFAULT 'medium'",
    "department": "TEXT NOT NULL DEFAULT 'general'",
    "assigned_to": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

with sqlite3.connect(DB_PATH) as conn:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(queries)")
    }

    for column, definition in new_columns.items():
        if column not in existing:
            conn.execute(
                f"ALTER TABLE queries ADD COLUMN {column} {definition}"
            )
            print(f"Added: {column}")
        else:
            print(f"Already exists: {column}")

    conn.execute("""
        UPDATE queries
        SET created_at = COALESCE(
            created_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        ),
        updated_at = COALESCE(
            updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        )
        WHERE created_at IS NULL OR updated_at IS NULL
    """)

    conn.commit()

print("Migration completed successfully.")
