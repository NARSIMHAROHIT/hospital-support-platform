
from contextlib import closing

from app.core.database import get_db


def create_nurse_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nurse_invitations (
            invitation_id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            full_name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,

            invited_by_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,

            accepted_at TEXT,
            accepted_user_id TEXT,
            revoked_at TEXT,

            FOREIGN KEY (invited_by_user_id)
                REFERENCES users(user_id),

            FOREIGN KEY (accepted_user_id)
                REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS nurse_profiles (
            user_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            created_at TEXT NOT NULL,

            FOREIGN KEY (user_id)
                REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS
            idx_nurse_invitation_email
        ON nurse_invitations(email);

        CREATE INDEX IF NOT EXISTS
            idx_nurse_invitation_expiry
        ON nurse_invitations(expires_at);
    """)


def main():
    with closing(get_db()) as conn:
        create_nurse_tables(conn)
        conn.commit()

    print("Nurse invitation tables created successfully.")


if __name__ == "__main__":
    main()
