
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.care_access import authorize_record_action
from scripts.create_care_team import create_care_team_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE patients (
            patient_id TEXT PRIMARY KEY
        );

        CREATE TABLE doctors (
            doctor_id TEXT PRIMARY KEY,
            is_active INTEGER NOT NULL
        );

        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            patient_id TEXT,
            doctor_id TEXT,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL
        );
        CREATE TABLE doctor_slots (
            slot_id TEXT PRIMARY KEY,
            doctor_id TEXT,
            starts_at TEXT,
            ends_at TEXT
        );

        CREATE TABLE appointments (
            appointment_id TEXT PRIMARY KEY,
            patient_id TEXT,
            doctor_id TEXT,
            slot_id TEXT,
            status TEXT
        );
    """)

    create_care_team_tables(conn)

    conn.executemany(
        "INSERT INTO patients VALUES (?)",
        [("patient-a",), ("patient-b",)],
    )

    conn.executemany(
        "INSERT INTO doctors VALUES (?, ?)",
        [
            ("doctor-a", 1),
            ("doctor-b", 1),
            ("doctor-inactive", 0),
        ],
    )

    conn.executemany("""
        INSERT INTO users
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("patient-user", "patient-a", None, "patient", 1),
        ("doctor-user", None, "doctor-a", "doctor", 1),
        ("other-doctor", None, "doctor-b", "doctor", 1),
        ("inactive-doctor", None, "doctor-inactive", "doctor", 1),
        ("nurse-user", None, None, "nurse", 1),
        ("admin-user", None, None, "admin", 1),
    ])

    conn.commit()

    yield conn
    conn.close()


def user(role, user_id, patient_id=None, doctor_id=None):
    return {
        "role": role,
        "user_id": user_id,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
    }


def assign(db, staff_user_id):
    db.execute("""
        INSERT INTO care_team_assignments (
            assignment_id,
            patient_id,
            staff_user_id,
            assigned_by_user_id
        )
        VALUES (?, ?, ?, ?)
    """, (
        f"assignment-{staff_user_id}",
        "patient-a",
        staff_user_id,
        "admin-user",
    ))
    db.commit()


def denied_status(db, account, patient_id, action):
    with pytest.raises(HTTPException) as error:
        authorize_record_action(
            db, account, patient_id, action
        )

    return error.value.status_code


def test_patient_can_access_only_own_records(db):
    patient = user(
        "patient", "patient-user", patient_id="patient-a"
    )

    authorize_record_action(
        db, patient, "patient-a", "records:read"
    )
    authorize_record_action(
        db, patient, "patient-a", "records:upload"
    )

    assert denied_status(
        db, patient, "patient-b", "records:read"
    ) == 404


def test_assigned_doctor_can_access_patient(db):
    assign(db, "doctor-user")

    doctor = user(
        "doctor", "doctor-user", doctor_id="doctor-a"
    )

    authorize_record_action(
        db, doctor, "patient-a", "records:read"
    )
    authorize_record_action(
        db, doctor, "patient-a", "notes:create"
    )


def test_unassigned_doctor_is_denied(db):
    doctor = user(
        "doctor", "other-doctor", doctor_id="doctor-b"
    )

    assert denied_status(
        db, doctor, "patient-a", "records:read"
    ) == 404


def test_nurse_can_read_but_not_create_doctor_notes(db):
    assign(db, "nurse-user")

    nurse = user("nurse", "nurse-user")

    authorize_record_action(
        db, nurse, "patient-a", "records:read"
    )
    authorize_record_action(
        db, nurse, "patient-a", "notes:read_signed"
    )

    assert denied_status(
        db, nurse, "patient-a", "notes:create"
    ) == 403


def test_revoked_assignment_denies_access(db):
    assign(db, "doctor-user")

    db.execute("""
        UPDATE care_team_assignments
        SET revoked_at = ?
        WHERE staff_user_id = ?
    """, (
        datetime.now(timezone.utc).isoformat(),
        "doctor-user",
    ))
    db.commit()

    doctor = user(
        "doctor", "doctor-user", doctor_id="doctor-a"
    )

    assert denied_status(
        db, doctor, "patient-a", "records:read"
    ) == 404


def test_inactive_doctor_cannot_access_records(db):
    assign(db, "inactive-doctor")

    doctor = user(
        "doctor",
        "inactive-doctor",
        doctor_id="doctor-inactive",
    )

    assert denied_status(
        db, doctor, "patient-a", "records:read"
    ) == 404


def test_admin_has_no_clinical_access_by_default(db):
    admin = user("admin", "admin-user")

    assert denied_status(
        db, admin, "patient-a", "records:read"
    ) == 403
