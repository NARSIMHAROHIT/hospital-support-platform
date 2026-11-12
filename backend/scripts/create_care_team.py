
from contextlib import closing

from app.core.database import get_db


def create_care_team_tables(conn):
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS care_team_assignments (
            assignment_id TEXT PRIMARY KEY,

            patient_id TEXT NOT NULL,
            staff_user_id TEXT NOT NULL,
            assigned_by_user_id TEXT NOT NULL,

            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),

            revoked_at TEXT,
            revoked_by_user_id TEXT,

            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id),

            FOREIGN KEY (staff_user_id)
                REFERENCES users(user_id),

            FOREIGN KEY (assigned_by_user_id)
                REFERENCES users(user_id),

            FOREIGN KEY (revoked_by_user_id)
                REFERENCES users(user_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_one_active_care_team_assignment
        ON care_team_assignments (
            patient_id,
            staff_user_id
        )
        WHERE revoked_at IS NULL;

        CREATE INDEX IF NOT EXISTS
            idx_care_team_patient
        ON care_team_assignments(patient_id);

        CREATE INDEX IF NOT EXISTS
            idx_care_team_staff
        ON care_team_assignments(staff_user_id);
    """)


def main():
    with closing(get_db()) as conn:
        create_care_team_tables(conn)
        conn.commit()

    print("Care-team assignment tables ready.")


if __name__ == "__main__":
    main()
