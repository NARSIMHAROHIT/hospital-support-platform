
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import clinical_patients
from scripts.create_care_team import create_care_team_tables


@pytest.fixture
def clinical_client(tmp_path, monkeypatch):
    db_path = tmp_path / "clinical_patients.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    with connect() as conn:
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
                ("p1", "Alice Stone"),
                ("p2", "Ben Jones"),
                ("p3", "Clara Reed"),
            ],
        )

        conn.executemany(
            "INSERT INTO doctors VALUES (?, ?)",
            [
                ("d1", 1),
                ("d2", 1),
                ("d3", 0),
            ],
        )

        conn.executemany("""
            INSERT INTO users
            VALUES (?, ?, ?, ?, ?)
        """, [
            ("admin1", None, None, "admin", 1),
            ("doctor1", None, "d1", "doctor", 1),
            ("doctor2", None, "d2", "doctor", 1),
            ("doctor3", None, "d3", "doctor", 1),
            ("nurse1", None, None, "nurse", 1),
            ("patient1", "p1", None, "patient", 1),
        ])

        conn.executemany("""
            INSERT INTO care_team_assignments (
                assignment_id,
                patient_id,
                staff_user_id,
                assigned_by_user_id
            )
            VALUES (?, ?, ?, 'admin1')
        """, [
            ("a1", "p1", "doctor1"),
            ("a2", "p2", "doctor1"),
            ("a3", "p3", "nurse1"),
        ])

        conn.commit()

    current = {
        "user": {
            "user_id": "doctor1",
            "role": "doctor",
            "doctor_id": "d1",
        }
    }

    monkeypatch.setattr(
        clinical_patients,
        "get_db",
        connect,
    )

    # Test-only fake session identity.
    # Production continues to use get_current_user.
    monkeypatch.setattr(
        clinical_patients,
        "get_current_user",
        lambda token: current["user"],
    )

    with TestClient(app) as client:
        client.cookies.set(
            "hospital_session",
            "test-session",
        )
        yield client, connect, current


def test_doctor_sees_only_assigned_patients(clinical_client):
    client, _, _ = clinical_client

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 2

    ids = {
        p["patient_id"]
        for p in response.json()["patients"]
    }

    assert ids == {"p1", "p2"}


def test_search_by_patient_name(clinical_client):
    client, _, _ = clinical_client

    response = client.get(
        "/clinical/my-patients",
        params={"q": "ali"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["patients"][0]["full_name"] == (
        "Alice Stone"
    )


def test_pagination(clinical_client):
    client, _, _ = clinical_client

    response = client.get(
        "/clinical/my-patients",
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["patients"]) == 1
    assert response.json()["patients"][0]["patient_id"] == "p2"


def test_doctor_can_open_assigned_patient(clinical_client):
    client, _, _ = clinical_client

    response = client.get("/clinical/my-patients/p1")

    assert response.status_code == 200
    assert response.json()["full_name"] == "Alice Stone"


def test_doctor_cannot_open_unassigned_patient(clinical_client):
    client, _, _ = clinical_client

    response = client.get("/clinical/my-patients/p3")

    assert response.status_code == 404


def test_nurse_sees_only_own_assigned_patient(clinical_client):
    client, _, current = clinical_client

    current["user"] = {
        "user_id": "nurse1",
        "role": "nurse",
    }

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["patients"][0]["patient_id"] == "p3"

    denied = client.get("/clinical/my-patients/p1")
    assert denied.status_code == 404


def test_revoked_assignment_removes_access(clinical_client):
    client, connect, _ = clinical_client

    with connect() as conn:
        conn.execute("""
            UPDATE care_team_assignments
            SET revoked_at = '2026-11-07T12:00:00Z'
            WHERE assignment_id = 'a1'
        """)
        conn.commit()

    response = client.get("/clinical/my-patients")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    denied = client.get("/clinical/my-patients/p1")

    assert denied.status_code == 404


def test_missing_session_is_rejected(clinical_client):
    client, _, _ = clinical_client

    client.cookies.clear()

    response = client.get("/clinical/my-patients")

    assert response.status_code == 401


@pytest.mark.parametrize("role", ["patient", "admin"])
def test_nonclinical_roles_are_rejected(
    clinical_client,
    role,
):
    client, _, current = clinical_client

    current["user"] = {
        "user_id": "patient1" if role == "patient" else "admin1",
        "role": role,
        "patient_id": "p1" if role == "patient" else None,
    }

    response = client.get("/clinical/my-patients")

    assert response.status_code == 403


def test_inactive_doctor_is_rejected(clinical_client):
    client, _, current = clinical_client

    current["user"] = {
        "user_id": "doctor3",
        "role": "doctor",
        "doctor_id": "d3",
    }

    response = client.get("/clinical/my-patients")

    assert response.status_code == 403
