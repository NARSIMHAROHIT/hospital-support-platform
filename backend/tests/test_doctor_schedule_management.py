
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import doctors, doctor_schedule_management


@pytest.fixture
def schedule_client(tmp_path, monkeypatch):
    db_path = tmp_path / "schedule_test.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    start = (
        datetime.now(timezone.utc) + timedelta(days=10)
    ).replace(hour=9, minute=0, second=0, microsecond=0)

    end = start + timedelta(minutes=30)

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
        """)

        conn.executemany(
            "INSERT INTO doctors VALUES (?, 1)",
            [("doctor-a",), ("doctor-b",)],
        )

        conn.execute("""
            INSERT INTO doctor_slots
            VALUES (?, ?, ?, ?)
        """, (
            "slot-a",
            "doctor-a",
            start.isoformat(),
            end.isoformat(),
        ))

        conn.commit()

    monkeypatch.setattr(
        doctor_schedule_management,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        doctors,
        "get_db",
        connect,
    )

    app.dependency_overrides[
        doctor_schedule_management.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-a",
    }

    app.dependency_overrides[
        doctor_schedule_management.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect, start, end
    finally:
        app.dependency_overrides.pop(
            doctor_schedule_management.require_doctor,
            None,
        )
        app.dependency_overrides.pop(
            doctor_schedule_management.check_request_origin,
            None,
        )


def test_doctor_can_create_slot(schedule_client):
    client, connect, start, end = schedule_client

    new_start = start + timedelta(hours=2)
    new_end = new_start + timedelta(minutes=30)

    response = client.post(
        "/doctor/schedule/slots",
        json={
            "starts_at": new_start.isoformat(),
            "ends_at": new_end.isoformat(),
        },
    )

    assert response.status_code == 201
    assert response.json()["availability"] == "available"

    with connect() as conn:
        result = conn.execute("""
            SELECT doctor_id
            FROM doctor_slots
            WHERE slot_id = ?
        """, (response.json()["slot_id"],)).fetchone()

    assert result["doctor_id"] == "doctor-a"


def test_doctor_cannot_create_overlapping_slot(schedule_client):
    client, _, start, end = schedule_client

    response = client.post(
        "/doctor/schedule/slots",
        json={
            "starts_at": (
                start + timedelta(minutes=15)
            ).isoformat(),
            "ends_at": (
                end + timedelta(minutes=15)
            ).isoformat(),
        },
    )

    assert response.status_code == 409


def test_doctor_can_block_available_slot(schedule_client):
    client, connect, _, _ = schedule_client

    response = client.patch(
        "/doctor/schedule/slots/slot-a/block"
    )

    assert response.status_code == 200
    assert response.json()["availability"] == "blocked"

    with connect() as conn:
        block = conn.execute("""
            SELECT slot_id
            FROM doctor_slot_blocks
            WHERE slot_id = 'slot-a'
        """).fetchone()

    assert block is not None


def test_booked_slot_cannot_be_blocked(schedule_client):
    client, connect, _, _ = schedule_client

    with connect() as conn:
        conn.execute("""
            INSERT INTO appointments
            VALUES (?, ?, ?, ?, ?)
        """, (
            "appointment-a",
            "patient-a",
            "doctor-a",
            "slot-a",
            "booked",
        ))
        conn.commit()

    response = client.patch(
        "/doctor/schedule/slots/slot-a/block"
    )

    assert response.status_code == 409

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*)
            FROM doctor_slot_blocks
        """).fetchone()[0]

    assert count == 0


def test_other_doctor_cannot_block_slot(schedule_client):
    client, connect, _, _ = schedule_client

    app.dependency_overrides[
        doctor_schedule_management.require_doctor
    ] = lambda: {
        "role": "doctor",
        "doctor_id": "doctor-b",
    }

    response = client.patch(
        "/doctor/schedule/slots/slot-a/block"
    )

    assert response.status_code == 404

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*)
            FROM doctor_slot_blocks
        """).fetchone()[0]

    assert count == 0


def test_blocked_slots_hidden_from_patients(schedule_client):
    client, connect, _, _ = schedule_client

    before = client.get("/doctors/doctor-a/slots")
    assert before.status_code == 200

    assert "slot-a" in [
        slot["slot_id"] for slot in before.json()
    ]

    with connect() as conn:
        conn.execute("""
            INSERT INTO doctor_slot_blocks
            VALUES (?, ?)
        """, (
            "slot-a",
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()

    after = client.get("/doctors/doctor-a/slots")

    assert after.status_code == 200

    assert "slot-a" not in [
        slot["slot_id"] for slot in after.json()
    ]
