
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import appointments


@pytest.fixture
def test_db(monkeypatch):
    conn = sqlite3.connect(
        ":memory:",
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE appointments (
            appointment_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            doctor_id TEXT NOT NULL,
            slot_id TEXT NOT NULL,
            status TEXT NOT NULL
        );

        INSERT INTO appointments VALUES
        (
            'appointment-b',
            'patient-b',
            'doctor-1',
            'slot-1',
            'booked'
        );
    """)

    # Return the actual SQLite connection.
    # contextlib.closing(conn) will call conn.close(),
    # so intercept that for this isolated test.
    class TestConnection:
        def execute(self, *args, **kwargs):
            return conn.execute(*args, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(
        appointments,
        "get_db",
        lambda: TestConnection(),
    )

    app.dependency_overrides[
        appointments.require_patient
    ] = lambda: {
        "patient_id": "patient-a",
        "role": "patient",
    }

    app.dependency_overrides[
        appointments.check_request_origin
    ] = lambda: None

    yield conn

    app.dependency_overrides.pop(
        appointments.require_patient, None
    )
    app.dependency_overrides.pop(
        appointments.check_request_origin, None
    )
    conn.close()


def test_cannot_cancel_another_patients_appointment(test_db):
    with TestClient(app) as client:
        response = client.patch(
            "/my/appointments/appointment-b/cancel",
        )

    assert response.status_code == 404

    row = test_db.execute("""
        SELECT status
        FROM appointments
        WHERE appointment_id = 'appointment-b'
    """).fetchone()

    assert row["status"] == "booked"


def test_cannot_reschedule_another_patients_appointment(test_db):
    with TestClient(app) as client:
        response = client.patch(
            "/my/appointments/appointment-b/reschedule",
            json={"new_slot_id": "slot-2"},
        )

    assert response.status_code == 404

    row = test_db.execute("""
        SELECT slot_id, status
        FROM appointments
        WHERE appointment_id = 'appointment-b'
    """).fetchone()

    assert row["slot_id"] == "slot-1"
    assert row["status"] == "booked"
