
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.care_access import authorize_record_action
from app.routers import clinical_patients
from scripts.create_care_team import create_care_team_tables


@pytest.fixture
def appointment_client(tmp_path, monkeypatch):
    db_path = tmp_path / "appointment_access.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    with closing(connect()) as conn:
        conn.executescript("""
            CREATE TABLE patients (
                patient_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL
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
            "INSERT INTO patients VALUES (?, ?)",
            [
                ("p1", "Alex Morgan"),
                ("p2", "Jamie Lee"),
            ],
        )

        conn.executemany(
            "INSERT INTO doctors VALUES (?, ?)",
            [
                ("d1", 1),
                ("d2", 1),
            ],
        )

        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            [
                ("admin1", None, None, "admin", 1),
                ("doc1", None, "d1", "doctor", 1),
                ("doc2", None, "d2", "doctor", 1),
                ("nurse1", None, None, "nurse", 1),
            ],
        )

        conn.executemany(
            "INSERT INTO doctor_slots VALUES (?, ?, ?, ?)",
            [
                (
                    "s1",
                    "d1",
                    tomorrow.isoformat(),
                    (tomorrow + timedelta(minutes=30)).isoformat(),
                ),
                (
                    "s2",
                    "d1",
                    (tomorrow + timedelta(hours=1)).isoformat(),
                    (tomorrow + timedelta(minutes=90)).isoformat(),
                ),
                (
                    "s3",
                    "d2",
                    tomorrow.isoformat(),
                    (tomorrow + timedelta(minutes=30)).isoformat(),
                ),
            ],
        )

        conn.executemany(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?)",
            [
                ("a1", "p1", "d1", "s1", "booked"),
                ("a3", "p2", "d2", "s3", "booked"),
            ],
        )

        conn.commit()

    current = {
        "user": {
            "user_id": "doc1",
            "doctor_id": "d1",
            "role": "doctor",
        }
    }

    monkeypatch.setattr(
        clinical_patients,
        "get_db",
        connect,
    )

    # Simulate a verified login session for tests.
    monkeypatch.setattr(
        clinical_patients,
        "get_current_user",
        lambda token: current["user"],
    )

    with TestClient(app) as client:
        client.cookies.set(
            "hospital_session",
            "fictional-test-session",
        )

        yield client, connect, current


def test_booking_automatically_adds_patient(appointment_client):
    client, _, _ = appointment_client

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    patient = response.json()["patients"][0]

    assert patient["patient_id"] == "p1"
    assert patient["access_source"] == "appointment"

    details = client.get("/clinical/my-patients/p1")

    assert details.status_code == 200


def test_booking_grants_record_permission(appointment_client):
    _, connect, current = appointment_client

    with closing(connect()) as conn:
        authorize_record_action(
            conn,
            current["user"],
            "p1",
            "records:read",
        )

        authorize_record_action(
            conn,
            current["user"],
            "p1",
            "notes:create",
        )


def test_cancelling_booking_removes_access(appointment_client):
    client, connect, _ = appointment_client

    with closing(connect()) as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'a1'
        """)

        conn.commit()

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 0

    details = client.get("/clinical/my-patients/p1")

    assert details.status_code == 404


def test_second_booking_preserves_access(appointment_client):
    client, connect, _ = appointment_client

    with closing(connect()) as conn:
        conn.execute("""
            INSERT INTO appointments
            VALUES ('a2', 'p1', 'd1', 's2', 'booked')
        """)

        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'a1'
        """)

        conn.commit()

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_recent_completed_visit_retains_access(
    appointment_client,
):
    client, connect, _ = appointment_client

    with closing(connect()) as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'completed'
            WHERE appointment_id = 'a1'
        """)

        conn.commit()

    response = client.get("/clinical/my-patients/p1")

    assert response.status_code == 200


def test_old_completed_visit_expires(appointment_client):
    client, connect, _ = appointment_client

    old_date = (
        datetime.now(timezone.utc)
        - timedelta(days=45)
    )

    with closing(connect()) as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'completed'
            WHERE appointment_id = 'a1'
        """)

        conn.execute("""
            UPDATE doctor_slots
            SET starts_at = ?, ends_at = ?
            WHERE slot_id = 's1'
        """, (
            old_date.isoformat(),
            (old_date + timedelta(minutes=30)).isoformat(),
        ))

        conn.commit()

    response = client.get("/clinical/my-patients/p1")

    assert response.status_code == 404


def test_other_doctor_cannot_view_patient(
    appointment_client,
):
    client, _, current = appointment_client

    current["user"] = {
        "user_id": "doc2",
        "doctor_id": "d2",
        "role": "doctor",
    }

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    assert (
        response.json()["patients"][0]["patient_id"]
        == "p2"
    )

    details = client.get("/clinical/my-patients/p1")

    assert details.status_code == 404


def test_nurse_not_automatically_assigned(
    appointment_client,
):
    client, _, current = appointment_client

    current["user"] = {
        "user_id": "nurse1",
        "role": "nurse",
    }

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_manual_assignment_still_works(
    appointment_client,
):
    client, connect, _ = appointment_client

    with closing(connect()) as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'a1'
        """)

        conn.execute("""
            INSERT INTO care_team_assignments (
                assignment_id,
                patient_id,
                staff_user_id,
                assigned_by_user_id
            )
            VALUES ('manual1', 'p1', 'doc1', 'admin1')
        """)

        conn.commit()

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    assert (
        response.json()["patients"][0]["access_source"]
        == "care_team"
    )
