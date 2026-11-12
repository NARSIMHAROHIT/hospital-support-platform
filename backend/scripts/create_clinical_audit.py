
from contextlib import closing

from app.core.database import get_db


def create_clinical_audit_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clinical_audit_events (
            audit_id TEXT PRIMARY KEY,

            actor_user_id TEXT NOT NULL,

            actor_role TEXT NOT NULL
                CHECK (
                    actor_role IN (
                        'doctor',
                        'patient',
                        'nurse',
                        'admin',
                        'system'
                    )
                ),

            patient_id TEXT,
            note_id TEXT,
            appointment_id TEXT,

            event_type TEXT NOT NULL
                CHECK (
                    event_type IN (
                        'note_created',
                        'note_edited',
                        'note_signed',
                        'note_addendum_added',
                        'note_released',
                        'note_revoked',
                        'doctor_note_viewed',
                        'patient_note_viewed',
                        'doctor_notes_listed',
                        'patient_notes_listed',
                        'medical_document_downloaded'
                    )
                ),

            outcome TEXT NOT NULL DEFAULT 'success'
                CHECK (outcome IN ('success', 'denied')),

            occurred_at TEXT NOT NULL,

            FOREIGN KEY (actor_user_id)
                REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_clinical_audit_patient
        ON clinical_audit_events (
            patient_id,
            occurred_at
        );

        CREATE INDEX IF NOT EXISTS
            idx_clinical_audit_actor
        ON clinical_audit_events (
            actor_user_id,
            occurred_at
        );

        CREATE INDEX IF NOT EXISTS
            idx_clinical_audit_note
        ON clinical_audit_events (
            note_id,
            occurred_at
        );

        CREATE INDEX IF NOT EXISTS
            idx_clinical_audit_event
        ON clinical_audit_events (
            event_type,
            occurred_at
        );
    """)


def main():
    with closing(get_db()) as conn:
        create_clinical_audit_tables(conn)
        conn.commit()

    print("Clinical audit tables created successfully.")


if __name__ == "__main__":
    main()
