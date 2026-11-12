import os
from contextlib import closing
from uuid import uuid4

from argon2 import PasswordHasher
from app.core.database import get_db

hasher = PasswordHasher()

PATIENT_EMAIL = "demo.patient@hospital.test"
DOCTOR_EMAIL = "maya.patel@hospital.test"


def main():
    patient_password = os.getenv("DEMO_PATIENT_PASSWORD", "")
    doctor_password = os.getenv("DEMO_DOCTOR_PASSWORD", "")

    if len(patient_password) < 16 or len(doctor_password) < 16:
        raise SystemExit(
            "Set DEMO_PATIENT_PASSWORD and DEMO_DOCTOR_PASSWORD "
            "to passwords of at least 16 characters."
        )

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        doctor = conn.execute(
            "SELECT doctor_id FROM doctors WHERE full_name = ?",
            ("Dr. Maya Patel",)
        ).fetchone()

        if not doctor:
            raise RuntimeError("Run doctor schedule seeding first.")

        patient = conn.execute(
            "SELECT patient_id FROM patients WHERE email = ?",
            (PATIENT_EMAIL,)
        ).fetchone()

        if patient:
            patient_id = patient["patient_id"]
        else:
            patient_id = str(uuid4())
            conn.execute("""
                INSERT INTO patients
                    (patient_id, full_name, email)
                VALUES (?, ?, ?)
            """, (
                patient_id,
                "Demo Patient",
                PATIENT_EMAIL
            ))

        accounts = [
            (
                PATIENT_EMAIL,
                patient_password,
                "patient",
                patient_id,
                None,
            ),
            (
                DOCTOR_EMAIL,
                doctor_password,
                "doctor",
                None,
                doctor["doctor_id"],
            ),
        ]

        for email, password, role, pid, did in accounts:
            existing = conn.execute(
                "SELECT user_id, role FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if existing:
                if existing["role"] != role:
                    raise RuntimeError(
                        f"Account has unexpected role: {email}"
                    )
                print(f"Account already exists: {email}")
                continue

            conn.execute("""
                INSERT INTO users (
                    user_id, patient_id, doctor_id,
                    email, password_hash, role, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (
                str(uuid4()),
                pid,
                did,
                email,
                hasher.hash(password),
                role,
            ))

            print(f"Created {role} account: {email}")

        conn.commit()

    print("Demo accounts ready. Passwords were not logged.")


if __name__ == "__main__":
    main()
