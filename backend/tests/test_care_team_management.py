
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.care_access import authorize_record_action
from app.routers import care_team_management
from scripts.create_care_team import create_care_team_tables


@pytest.fixture
def care_team_client(tmp_path, monkeypatch):
    db_path = tmp_path / "care_team_api.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    with connect() as conn:
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
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );
        """)

        create_care_team_tables(conn)

        conn.execute("""
            INSERT INTO patients VALUES ('patient-a')
        """)

        conn.executemany(
            "INSERT INTO doctors VALUES (?, ?)",
            [
                ("doctor-a", 1),
                ("doctor-inactive", 0),
            ],
        )

        conn.executemany("""
            INSERT INTO users
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (
                "admin-a", None, None,
                "admin@example.com", "admin", 1,
            ),
            (
                "patient-user", "patient-a", None,
                "patient@example.com", "patient", 1,
            ),
            (
                "doctor-user", None, "doctor-a",
                "doctor@example.com", "doctor", 1,
            ),
            (
                "inactive-doctor", None, "doctor-inactive",
                "inactive-doctor@example.com", "doctor", 1,
            ),
            (
                "nurse-user", None, None,
                "nurse@example.com", "nurse", 1,
            ),
            (
                "inactive-nurse", None, None,
                "inactive-nurse@example.com", "nurse", 0,
            ),
        ])

        conn.commit()

    monkeypatch.setattr(
        care_team_management,
        "get_db",
        connect,
    )

    app.dependency_overrides[
        care_team_management.require_admin
    ] = lambda: {
        "user_id": "admin-a",
        "role": "admin",
    }

    app.dependency_overrides[
        care_team_management.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect
    finally:
        app.dependency_overrides.pop(
            care_team_management.require_admin,
            None,
        )
        app.dependency_overrides.pop(
            care_team_management.check_request_origin,
            None,
        )


def assign(client, staff_user_id="doctor-user"):
    return client.post(
        "/admin/care-team/assignments",
        json={
            "patient_id": "patient-a",
            "staff_user_id": staff_user_id,
        },
    )


def test_admin_can_assign_doctor(care_team_client):
    client, connect = care_team_client

    response = assign(client)

    assert response.status_code == 201
    assert response.json()["status"] == "active"
    assert response.json()["staff_role"] == "doctor"

    with connect() as conn:
        authorize_record_action(
            conn,
            {
                "user_id": "doctor-user",
                "doctor_id": "doctor-a",
                "role": "doctor",
            },
            "patient-a",
            "records:read",
        )

    listing = client.get(
        "/admin/care-team/assignments",
        params={"patient_id": "patient-a"},
    )

    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_duplicate_assignment_rejected(care_team_client):
    client, _ = care_team_client

    first = assign(client)
    second = assign(client)

    assert first.status_code == 201
    assert second.status_code == 409


def test_nurse_access_revoked(care_team_client):
    client, connect = care_team_client

    response = assign(client, "nurse-user")
    assert response.status_code == 201

    with connect() as conn:
        authorize_record_action(
            conn,
            {
                "user_id": "nurse-user",
                "role": "nurse",
            },
            "patient-a",
            "notes:read_signed",
        )

    assignment_id = response.json()["assignment_id"]

    revoked = client.patch(
        f"/admin/care-team/assignments/{assignment_id}/revoke"
    )

    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    with connect() as conn:
        with pytest.raises(HTTPException) as error:
            authorize_record_action(
                conn,
                {
                    "user_id": "nurse-user",
                    "role": "nurse",
                },
                "patient-a",
                "notes:read_signed",
            )

    assert error.value.status_code == 404


def test_inactive_doctor_rejected(care_team_client):
    client, _ = care_team_client

    response = assign(client, "inactive-doctor")

    assert response.status_code == 409


def test_inactive_nurse_rejected(care_team_client):
    client, _ = care_team_client

    response = assign(client, "inactive-nurse")

    assert response.status_code == 409


def test_nonclinical_role_rejected(care_team_client):
    client, _ = care_team_client

    response = assign(client, "patient-user")

    assert response.status_code == 422


def test_reassignment_after_revocation(care_team_client):
    client, _ = care_team_client

    first = assign(client)
    assert first.status_code == 201

    assignment_id = first.json()["assignment_id"]

    revoked = client.patch(
        f"/admin/care-team/assignments/{assignment_id}/revoke"
    )
    assert revoked.status_code == 200

    second = assign(client)

    assert second.status_code == 201
    assert second.json()["assignment_id"] != assignment_id


def test_assignment_requires_admin(care_team_client):
    client, _ = care_team_client

    app.dependency_overrides.pop(
        care_team_management.require_admin,
        None,
    )

    response = assign(client)

    assert response.status_code in (401, 403)
