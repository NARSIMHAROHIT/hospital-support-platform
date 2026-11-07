
import sqlite3
import uuid
import getpass
from pathlib import Path
from argon2 import PasswordHasher

DB_PATH = Path(__file__).resolve().parent.parent / "hospital.db"

hasher = PasswordHasher()

email = "alex.morgan@example.com"

with sqlite3.connect(DB_PATH) as conn:
    patient = conn.execute(
        "SELECT patient_id FROM patients WHERE email = ?",
        (email,)
    ).fetchone()

    if patient is None:
        raise SystemExit("Demo patient not found")

    password = getpass.getpass("Create demo password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        raise SystemExit("Passwords do not match")

    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")

    password_hash = hasher.hash(password)

    try:
        conn.execute("""
            INSERT INTO users
            (user_id, patient_id, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            patient[0],
            email,
            password_hash,
            "patient"
        ))
        conn.commit()

    except sqlite3.IntegrityError:
        raise SystemExit("Account already exists")

print("Demo patient account created successfully")
