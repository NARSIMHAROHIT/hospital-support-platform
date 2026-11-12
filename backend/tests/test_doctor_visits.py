
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import doctor_visits


@pytest.fixture
def visit_client(tmp_path, monkeypatch):
    db_path = tmp_path / "visits.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=2)
    future = now + timedelta(days=2)

    with connect() as conn:
        conn.executescript("""
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

            CREATE TABLE reschedule_requests (
                request_id TEXT PRIMARY KEY,
                appointment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                decided_at TEXT
            );
        """)

        conn.executemany("""
            INSERT INTO doctor_slots
            VALUES (?, ?, ?, ?)
        """, [
            (
                "past-slot",
                "doctor-a",
                past.isoformat(),
                (past + timedelta(minutes=30)).isoformat(),
            ),
            (
                "future-slot",
                "doctor-a",
                future.isoformat(),
                (future + timedelta(minutes=30)).isoformat(),
            ),
        ])

        conn.executemany("""
            INSERT INTO appointments
            VALUES (?, ?, ?, ?, ?)
        """, [
            (
                "past-appointment",
                "patient-a",
                "doctor-a",
                "past-slot",
                "booked",
            ),
            (
                "future-appointment",
                "patient-a",
                "doctor-a",
                "future-slot",
                "booked",
            ),
        ])

        conn.execute("""
            INSERT INTO reschedule_requests
            VALUES (?, ?, ?, ?)
        """, (
            "pending-request",
            "past-appointment",
            "pending",
            None,
        ))

        conn.commit()

    monkeypatch.setattr(doctor_visits, "get_db", connect)

    app.dependency_overrides[
        doctor_visits.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-a",
    }

    app.dependency_overrides[
        doctor_visits.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect
    finally:
        app.dependency_overrides.pop(
            doctor_visits.require_doctor, None
        )
        app.dependency_overrides.pop(
            doctor_visits.check_request_origin, None
        )


def test_doctor_can_complete_past_visit(visit_client):
    client, connect = visit_client

    response = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    with connect() as conn:
        status = conn.execute("""
            SELECT status FROM appointments
            WHERE appointment_id = 'past-appointment'
        """).fetchone()["status"]

    assert status == "completed"


def test_cannot_complete_future_visit(visit_client):
    client, connect = visit_client

    response = client.patch(
        "/doctor/appointments/future-appointment/complete"
    )

    assert response.status_code == 409

    with connect() as conn:
        status = conn.execute("""
            SELECT status FROM appointments
            WHERE appointment_id = 'future-appointment'
        """).fetchone()["status"]

    assert status == "booked"


def test_other_doctor_cannot_complete_visit(visit_client):
    client, connect = visit_client

    app.dependency_overrides[
        doctor_visits.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-b",
    }

    response = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    assert response.status_code == 404


def test_cannot_complete_same_visit_twice(visit_client):
    client, connect = visit_client

    first = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    second = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_completion_closes_pending_reschedule(visit_client):
    client, connect = visit_client

    response = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    assert response.status_code == 200

    with connect() as conn:
        request = conn.execute("""
            SELECT status, decided_at
            FROM reschedule_requests
            WHERE request_id = 'pending-request'
        """).fetchone()

    assert request["status"] == "cancelled"
    assert request["decided_at"] is not None


def test_cancelled_visit_cannot_be_completed(visit_client):
    client, connect = visit_client

    with connect() as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'past-appointment'
        """)
        conn.commit()

    response = client.patch(
        "/doctor/appointments/past-appointment/complete"
    )

    assert response.status_code == 409
