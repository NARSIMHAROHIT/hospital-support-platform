
from contextlib import closing

from app.core.database import get_db


def create_note_release_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doctor_note_releases (
            note_id TEXT PRIMARY KEY,
            released_by_user_id TEXT NOT NULL,
            released_at TEXT NOT NULL,
            revoked_at TEXT,
            revoked_by_user_id TEXT,

            FOREIGN KEY (note_id)
                REFERENCES doctor_clinical_notes(note_id),

            FOREIGN KEY (released_by_user_id)
                REFERENCES users(user_id),

            FOREIGN KEY (revoked_by_user_id)
                REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS doctor_note_release_events (
            event_id TEXT PRIMARY KEY,
            note_id TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            event_type TEXT NOT NULL
                CHECK (event_type IN ('released', 'revoked')),
            created_at TEXT NOT NULL,

            FOREIGN KEY (note_id)
                REFERENCES doctor_clinical_notes(note_id),

            FOREIGN KEY (actor_user_id)
                REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_note_release_events_note
        ON doctor_note_release_events(note_id);
    """)


def main():
    with closing(get_db()) as conn:
        create_note_release_tables(conn)
        conn.commit()

    print("Doctor note release tables created successfully.")


if __name__ == "__main__":
    main()
