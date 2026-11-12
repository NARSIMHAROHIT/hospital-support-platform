
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
    conn.execute("BEGIN IMMEDIATE")

    conn.execute("""
        CREATE TABLE appointments_new (
            appointment_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            doctor_id TEXT NOT NULL,
            slot_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked'
                CHECK (status IN (
                    'booked', 'cancelled', 'completed'
                )),
            created_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id),
            FOREIGN KEY (doctor_id)
                REFERENCES doctors(doctor_id),
            FOREIGN KEY (slot_id)
                REFERENCES doctor_slots(slot_id)
        )
    """)

    conn.execute("""
        INSERT INTO appointments_new
        SELECT appointment_id, patient_id, doctor_id,
               slot_id, status, created_at
        FROM appointments
    """)

    conn.execute("DROP TABLE appointments")
    conn.execute(
        "ALTER TABLE appointments_new RENAME TO appointments"
    )

    conn.execute("""
        CREATE UNIQUE INDEX unique_active_slot
        ON appointments(slot_id)
        WHERE status IN ('booked', 'completed')
    """)

    conn.commit()

print("Slot reuse migration completed successfully")
