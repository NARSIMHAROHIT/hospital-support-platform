
from contextlib import closing

from app.core.database import get_db


def create_document_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patient_documents (
            document_id TEXT PRIMARY KEY,

            patient_id TEXT NOT NULL,
            uploaded_by_user_id TEXT NOT NULL,

            original_filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            storage_key TEXT NOT NULL UNIQUE,

            uploaded_at TEXT NOT NULL,

            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id),

            FOREIGN KEY (uploaded_by_user_id)
                REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_patient_documents_owner
        ON patient_documents (
            patient_id,
            uploaded_at
        );
    """)


def main():
    with closing(get_db()) as conn:
        create_document_tables(conn)
        conn.commit()

    print("Patient document tables created successfully.")


if __name__ == "__main__":
    main()
