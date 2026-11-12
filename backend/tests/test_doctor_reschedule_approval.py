
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import doctor_portal


@pytest.fixture
def doctor_client(tmp_path, monkeypatch):
    db_path = tmp_path / "doctor_test.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    start = (
        datetime.now(timezone.utc) + timedelta(days=10)
    ).replace(hour=9, minute=0, second=0, microsecond=0)

    requested_start = start + timedelta(days=2)

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE doctors (
                doctor_id TEXT PRIMARY KEY,
                is_active INTEGER NOT NULL
            );

            CREATE TABLE doctor_slots (
                slot_id TEXT PRIMARY KEY,
                doctor_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL
            );

            CREATE TABLE appointments (
                appointment_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                status TEXT NOT NULL
            );


            CREATE TABLE doctor_slot_blocks (
                slot_id TEXT PRIMARY KEY,
                blocked_at TEXT NOT NULL,
                FOREIGN KEY (slot_id)
                    REFERENCES doctor_slots(slot_id)
            );

            CREATE TABLE reschedule_requests (
                request_id TEXT PRIMARY KEY,
                appointment_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                original_slot_id TEXT NOT NULL,
                requested_slot_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT
            );
        """)

        conn.executemany(
            "INSERT INTO doctors VALUES (?, 1)",
            [("doctor-a",), ("doctor-b",)],
        )

        conn.executemany("""
            INSERT INTO doctor_slots
            VALUES (?, ?, ?, ?)
        """, [
            (
                "slot-original",
                "doctor-a",
                start.isoformat(),
                (start + timedelta(minutes=30)).isoformat(),
            ),
            (
                "slot-requested",
                "doctor-a",
                requested_start.isoformat(),
                (
                    requested_start + timedelta(minutes=30)
                ).isoformat(),
            ),
        ])

        conn.execute("""
            INSERT INTO appointments
            VALUES (?, ?, ?, ?, ?)
        """, (
            "appointment-a",
            "patient-a",
            "doctor-a",
            "slot-original",
            "booked",
        ))

        conn.execute("""
            INSERT INTO reschedule_requests
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "request-a",
            "appointment-a",
            "patient-a",
            "doctor-a",
            "slot-original",
            "slot-requested",
            "pending",
            datetime.now(timezone.utc).isoformat(),
            None,
        ))

        conn.commit()

    monkeypatch.setattr(
        doctor_portal,
        "get_db",
        connect,
    )

    # Test-only authentication overrides.
    # Production authentication is unchanged.
    app.dependency_overrides[
        doctor_portal.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-a",
        "email": "doctor-a@example.com",
    }

    app.dependency_overrides[
        doctor_portal.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect
    finally:
        app.dependency_overrides.pop(
            doctor_portal.require_doctor, None
        )
        app.dependency_overrides.pop(
            doctor_portal.check_request_origin, None
        )


def get_state(connect):
    with connect() as conn:
        appointment = conn.execute("""
            SELECT slot_id, status
            FROM appointments
            WHERE appointment_id = 'appointment-a'
        """).fetchone()

        request = conn.execute("""
            SELECT status
            FROM reschedule_requests
            WHERE request_id = 'request-a'
        """).fetchone()

    return dict(appointment), request["status"]


def test_doctor_can_approve_request(doctor_client):
    client, connect = doctor_client

    response = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert response.status_code == 200

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-requested"
    assert appointment["status"] == "booked"
    assert status == "approved"


def test_doctor_can_reject_request(doctor_client):
    client, connect = doctor_client

    response = client.patch(
        "/doctor/reschedule-requests/request-a/reject"
    )

    assert response.status_code == 200

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-original"
    assert status == "rejected"


def test_other_doctor_cannot_approve(doctor_client):
    client, connect = doctor_client

    app.dependency_overrides[
        doctor_portal.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-b",
    }

    response = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert response.status_code == 404

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-original"
    assert status == "pending"


def test_occupied_slot_cannot_be_approved(doctor_client):
    client, connect = doctor_client

    with connect() as conn:
        conn.execute("""
            INSERT INTO appointments
            VALUES (?, ?, ?, ?, ?)
        """, (
            "appointment-other",
            "patient-b",
            "doctor-a",
            "slot-requested",
            "booked",
        ))
        conn.commit()

    response = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert response.status_code == 409

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-original"
    assert status == "pending"


def test_cancelled_appointment_cannot_be_approved(
    doctor_client,
):
    client, connect = doctor_client

    with connect() as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'appointment-a'
        """)
        conn.commit()

    response = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert response.status_code == 409

    appointment, status = get_state(connect)

    assert appointment["status"] == "cancelled"
    assert status == "pending"


def test_request_cannot_be_approved_twice(doctor_client):
    client, connect = doctor_client

    first = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    second = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert first.status_code == 200
    assert second.status_code == 409

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-requested"
    assert status == "approved"


def test_blocked_slot_cannot_be_approved(doctor_client):
    client, connect = doctor_client

    with connect() as conn:
        conn.execute("""
            INSERT INTO doctor_slot_blocks (
                slot_id,
                blocked_at
            )
            VALUES (?, ?)
        """, (
            "slot-requested",
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()

    response = client.patch(
        "/doctor/reschedule-requests/request-a/approve"
    )

    assert response.status_code == 409

    appointment, status = get_state(connect)

    assert appointment["slot_id"] == "slot-original"
    assert status == "pending"