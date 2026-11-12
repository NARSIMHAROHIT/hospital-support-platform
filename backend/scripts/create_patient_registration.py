
from contextlib import closing

from app.core.database import get_db


def main():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_patient_registrations (
                email TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                otp_hash TEXT NOT NULL,
                otp_expires_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                send_count INTEGER NOT NULL DEFAULT 1,
                window_started_at TEXT NOT NULL,
                last_sent_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()

    print("Patient registration table ready.")


if __name__ == "__main__":
    main()
