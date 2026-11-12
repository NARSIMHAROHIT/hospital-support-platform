import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LOCAL_DB = BACKEND_DIR / "hospital.db"

db_value = os.getenv("HOSPITAL_DB_PATH")

if not db_value:
    raise SystemExit(
        "ERROR: HOSPITAL_DB_PATH is required."
    )

DB_PATH = Path(db_value).expanduser().resolve()

if DB_PATH == LOCAL_DB.resolve():
    raise SystemExit(
        "ERROR: Refusing to modify the local hospital.db."
    )

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

MIGRATIONS = [
    "001_add_ticket_fields.py",
    "002_patients_doctors.py",
    "003_appointments.py",
    "004_allow_slot_reuse.py",
    "005_authentication.py",
]

SETUP_MODULES = [
    "scripts.create_patient_registration",
    "scripts.create_medical_records",
    "scripts.create_patient_documents",
    "scripts.create_care_team",
    "scripts.create_nurse_invitations",
    "scripts.create_doctor_clinical_notes",
    "scripts.create_note_releases",
    "scripts.create_clinical_audit",
    "scripts.create_reschedule_requests",
    "scripts.create_ai_chat_memory",
]

def run(*args):
    print("Running:", " ".join(args), flush=True)

    subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        check=True,
    )

def main():
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            initialized = conn.execute("""
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'demo_schema_ready'
            """).fetchone()

        if initialized:
            print("Demo database already initialized.")
            return

        raise SystemExit(
            "Database already exists but initialization "
            "is incomplete. Refusing to overwrite it."
        )

    print("Creating fresh fictional demo database")
    print("Database:", DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE queries (
                ticket_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conn.commit()

    for filename in MIGRATIONS:
        run(str(BACKEND_DIR / "migrations" / filename))

    for module in SETUP_MODULES:
        run("-m", module)

    with sqlite3.connect(DB_PATH) as conn:
        from app.routers.doctor_schedule_management import ensure_schedule_tables
        ensure_schedule_tables(conn)

        required = {
            "queries",
            "patients",
            "doctors",
            "doctor_slots",
            "doctor_slot_blocks",
            "appointments",
            "users",
            "sessions",
            "pending_patient_registrations",
            "patient_documents",
            "ai_conversations",
            "ai_chat_messages",
        }

        existing = {
            row[0]
            for row in conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'table'
            """)
        }

        missing = required - existing

        if missing:
            raise RuntimeError(
                f"Missing database tables: {sorted(missing)}"
            )

        conn.execute("""
            CREATE TABLE demo_schema_ready (
                initialized_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute(
            "INSERT INTO demo_schema_ready DEFAULT VALUES"
        )
        conn.commit()

    print("\nSUCCESS: Demo database initialized.")
    print("Tables created:", len(existing))
    print("No real patient data was copied.")

if __name__ == "__main__":
    main()
