
import secrets
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from argon2 import PasswordHasher

from app.core.database import get_db


hasher = PasswordHasher()

DEMO_ACCOUNTS = [
    {
        "name": "Dr. Maya Patel",
        "email": "maya.patel@hospital.test",
    },
    {
        "name": "Dr. James Wilson",
        "email": "james.wilson@hospital.test",
    },
    {
        "name": "Dr. Sarah Lee",
        "email": "sarah.lee@hospital.test",
    },
]


def main():
    print("Creating fictional doctor accounts...\n")

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        created = []

        try:
            for account in DEMO_ACCOUNTS:
                doctor = conn.execute("""
                    SELECT doctor_id
                    FROM doctors
                    WHERE full_name = ?
                      AND is_active = 1
                """, (account["name"],)).fetchone()

                if doctor is None:
                    print("Doctor not found:", account["name"])
                    continue

                existing = conn.execute("""
                    SELECT user_id
                    FROM users
                    WHERE email = ?
                       OR doctor_id = ?
                """, (
                    account["email"],
                    doctor["doctor_id"],
                )).fetchone()

                if existing:
                    print("Already exists:", account["name"])
                    continue

                password = secrets.token_urlsafe(18)

                conn.execute("""
                    INSERT INTO users (
                        user_id,
                        patient_id,
                        doctor_id,
                        email,
                        password_hash,
                        role,
                        is_active,
                        created_at
                    )
                    VALUES (?, NULL, ?, ?, ?, 'doctor', 1, ?)
                """, (
                    str(uuid4()),
                    doctor["doctor_id"],
                    account["email"],
                    hasher.hash(password),
                    datetime.now(timezone.utc).isoformat(),
                ))

                created.append({
                    "name": account["name"],
                    "email": account["email"],
                    "password": password,
                })

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    for account in created:
        print("\nDoctor:", account["name"])
        print("Email:", account["email"])
        print("Temporary password:", account["password"])

    print("\nAccounts created:", len(created))
    print("Local development accounts only.")


if __name__ == "__main__":
    import sys

    if "--create-demo-users" not in sys.argv:
        raise SystemExit(
            "Run with --create-demo-users "
            "to create fictional doctor accounts."
        )

    main()
