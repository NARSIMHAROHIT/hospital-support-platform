
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.routers.appointments import (
    parse_utc,
    verify_no_booking_conflicts,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE doctor_slots (
            slot_id TEXT PRIMARY KEY,
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
    """)

    # Use future times so the tests remain valid.
    start = datetime.now(timezone.utc) + timedelta(days=7)
    start = start.replace(
        hour=9, minute=0, second=0, microsecond=0
    )

    end = start + timedelta(minutes=30)

    conn.execute("""
        INSERT INTO doctor_slots
        (slot_id, starts_at, ends_at)
        VALUES (?, ?, ?)
    """, (
        "slot-1",
        start.isoformat(),
        end.isoformat(),
    ))

    conn.execute("""
        INSERT INTO appointments
        (appointment_id, patient_id, doctor_id, slot_id, status)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "appointment-1",
        "patient-a",
        "doctor-a",
        "slot-1",
        "booked",
    ))

    conn.commit()

    yield conn, start, end
    conn.close()


def check(conn, patient, doctor, start, end, exclude=None):
    conn.execute("BEGIN IMMEDIATE")

    try:
        verify_no_booking_conflicts(
            conn=conn,
            patient_id=patient,
            doctor_id=doctor,
            start_time=start,
            end_time=end,
            exclude_appointment_id=exclude,
        )
    finally:
        conn.rollback()


def test_patient_cannot_book_two_doctors_same_time(db):
    conn, start, end = db

    with pytest.raises(HTTPException) as error:
        check(
            conn,
            "patient-a",
            "doctor-b",
            start,
            end,
        )

    assert error.value.status_code == 409
    assert "already have an appointment" in error.value.detail


def test_doctor_cannot_have_two_patients_same_time(db):
    conn, start, end = db

    with pytest.raises(HTTPException) as error:
        check(
            conn,
            "patient-b",
            "doctor-a",
            start,
            end,
        )

    assert error.value.status_code == 409
    assert "Doctor already has" in error.value.detail


def test_partially_overlapping_booking_rejected(db):
    conn, start, end = db

    new_start = start + timedelta(minutes=15)
    new_end = end + timedelta(minutes=15)

    with pytest.raises(HTTPException) as error:
        check(
            conn,
            "patient-a",
            "doctor-b",
            new_start,
            new_end,
        )

    assert error.value.status_code == 409


def test_consecutive_appointments_allowed(db):
    conn, start, end = db

    new_start = end
    new_end = end + timedelta(minutes=30)

    check(
        conn,
        "patient-a",
        "doctor-b",
        new_start,
        new_end,
    )


def test_reschedule_excludes_current_appointment(db):
    conn, start, end = db

    check(
        conn,
        "patient-a",
        "doctor-a",
        start,
        end,
        exclude="appointment-1",
    )


def test_timestamp_normalization():
    timestamp = parse_utc("2026-11-10T09:00:00-06:00")

    assert timestamp == datetime(
        2026, 11, 10, 15, 0,
        tzinfo=timezone.utc,
    )
