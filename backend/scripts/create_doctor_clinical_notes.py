
from contextlib import closing

from app.core.database import get_db


def create_clinical_note_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doctor_clinical_notes (
            note_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            doctor_id TEXT NOT NULL,
            appointment_id TEXT NOT NULL,
            author_user_id TEXT NOT NULL,

            observations TEXT NOT NULL,
            assessment TEXT NOT NULL DEFAULT '',
            treatment_plan TEXT NOT NULL DEFAULT '',

            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'signed')),

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            signed_at TEXT,

            UNIQUE (appointment_id, author_user_id),

            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id),

            FOREIGN KEY (doctor_id)
                REFERENCES doctors(doctor_id),

            FOREIGN KEY (appointment_id)
                REFERENCES appointments(appointment_id),

            FOREIGN KEY (author_user_id)
                REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS doctor_note_addenda (
            addendum_id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            author_user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,

            FOREIGN KEY (note_id)
                REFERENCES doctor_clinical_notes(note_id),

            FOREIGN KEY (author_user_id)
                REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS doctor_note_events (
            event_id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            event_type TEXT NOT NULL
                CHECK (event_type IN (
                    'created',
                    'edited',
                    'signed',
                    'addendum_added'
                )),
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,

            FOREIGN KEY (note_id)
                REFERENCES doctor_clinical_notes(note_id),

            FOREIGN KEY (actor_user_id)
                REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_doctor_notes_patient
            ON doctor_clinical_notes(patient_id);

        CREATE INDEX IF NOT EXISTS idx_doctor_notes_author
            ON doctor_clinical_notes(author_user_id);

        CREATE INDEX IF NOT EXISTS idx_doctor_addenda_note
            ON doctor_note_addenda(note_id);

        CREATE INDEX IF NOT EXISTS idx_doctor_note_events
            ON doctor_note_events(note_id);
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS patient_note_releases (
            note_id TEXT PRIMARY KEY,
            released_by_user_id TEXT NOT NULL,
            released_at TEXT NOT NULL,

            FOREIGN KEY (note_id)
                REFERENCES doctor_clinical_notes(note_id),

            FOREIGN KEY (released_by_user_id)
                REFERENCES users(user_id)
        )
    """)


def main():
    with closing(get_db()) as conn:
        create_clinical_note_tables(conn)
        conn.commit()

    print("Doctor clinical notes tables created successfully.")


if __name__ == "__main__":
    main()
