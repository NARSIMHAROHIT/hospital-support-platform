
from contextlib import closing

from app.core.database import get_db


def main():
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if "doctor_id" not in columns:
            conn.execute("""
                ALTER TABLE users
                ADD COLUMN doctor_id TEXT
                REFERENCES doctors(doctor_id)
            """)

            print("Added doctor_id to users table.")
        else:
            print("doctor_id column already exists.")

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_users_unique_doctor_id
            ON users(doctor_id)
            WHERE doctor_id IS NOT NULL
        """)

        conn.commit()

    print("Doctor account migration complete.")


if __name__ == "__main__":
    main()
