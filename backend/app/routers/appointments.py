
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Cookie, HTTPException

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.appointments import (
    AppointmentCreate,
    AppointmentReschedule,
)

router = APIRouter(tags=["Appointments"])


@router.post("/appointments", status_code=201)
def book_appointment(booking: AppointmentCreate):
    appointment_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        patient = conn.execute(
            "SELECT 1 FROM patients WHERE patient_id = ?",
            (booking.patient_id,)
        ).fetchone()

        if patient is None:
            raise HTTPException(404, "Patient not found")

        slot = conn.execute("""
            SELECT s.slot_id
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            booking.slot_id,
            booking.doctor_id
        )).fetchone()

        if slot is None:
            raise HTTPException(404, "Doctor slot not found")

        try:
            conn.execute("""
                INSERT INTO appointments
                (appointment_id, patient_id, doctor_id, slot_id)
                VALUES (?, ?, ?, ?)
            """, (
                appointment_id,
                booking.patient_id,
                booking.doctor_id,
                booking.slot_id
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            raise HTTPException(409, "Slot already booked")

    return {
        "appointment_id": appointment_id,
        "patient_id": booking.patient_id,
        "doctor_id": booking.doctor_id,
        "slot_id": booking.slot_id,
        "status": "booked"
    }


@router.get("/appointments")
def list_appointments():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.status,
                p.full_name AS patient,
                d.full_name AS doctor,
                d.specialization,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN patients p ON a.patient_id = p.patient_id
            JOIN doctors d ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s ON a.slot_id = s.slot_id
            ORDER BY s.starts_at
        """).fetchall()

    return [dict(row) for row in rows]


@router.patch("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        appointment = conn.execute("""
            SELECT appointment_id, status
            FROM appointments
            WHERE appointment_id = ?
        """, (appointment_id,)).fetchone()

        if appointment is None:
            raise HTTPException(404, "Appointment not found")

        if appointment["status"] != "booked":
            raise HTTPException(
                409,
                "Only booked appointments can be cancelled"
            )

        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = ?
        """, (appointment_id,))

        conn.commit()

    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "message": "Appointment cancelled successfully"
    }


@router.patch("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: str,
    request: AppointmentReschedule
):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        appointment = conn.execute("""
            SELECT
                appointment_id,
                doctor_id,
                slot_id,
                status
            FROM appointments
            WHERE appointment_id = ?
        """, (appointment_id,)).fetchone()

        if appointment is None:
            raise HTTPException(404, "Appointment not found")

        if appointment["status"] != "booked":
            raise HTTPException(
                409,
                "Only booked appointments can be rescheduled"
            )

        if appointment["slot_id"] == request.new_slot_id:
            raise HTTPException(
                409,
                "New slot must be different"
            )

        new_slot = conn.execute("""
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            request.new_slot_id,
            appointment["doctor_id"]
        )).fetchone()

        if new_slot is None:
            raise HTTPException(
                404, "New doctor slot not found"
            )

        start_time = datetime.fromisoformat(
            new_slot["starts_at"]
        )

        if start_time <= datetime.now(timezone.utc):
            raise HTTPException(
                409,
                "Cannot reschedule into a past slot"
            )

        occupied = conn.execute("""
            SELECT 1
            FROM appointments
            WHERE slot_id = ?
              AND status IN ('booked', 'completed')
        """, (request.new_slot_id,)).fetchone()

        if occupied:
            raise HTTPException(
                409,
                "Requested slot is unavailable"
            )

        try:
            conn.execute("""
                UPDATE appointments
                SET slot_id = ?
                WHERE appointment_id = ?
            """, (
                request.new_slot_id,
                appointment_id
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                409,
                "Requested slot is unavailable"
            )

    return {
        "appointment_id": appointment_id,
        "status": "booked",
        "previous_slot_id": appointment["slot_id"],
        "new_slot_id": request.new_slot_id,
        "starts_at": new_slot["starts_at"],
        "ends_at": new_slot["ends_at"],
        "message": "Appointment rescheduled successfully"
    }


@router.get("/my/appointments")
def my_appointments(
    hospital_session: str | None = Cookie(default=None)
):
    user = get_current_user(hospital_session)

    if user["role"] != "patient" or not user["patient_id"]:
        raise HTTPException(403, "Patient access required")

    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.status,
                d.full_name AS doctor,
                d.specialization,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN doctors d ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s ON a.slot_id = s.slot_id
            WHERE a.patient_id = ?
            ORDER BY s.starts_at
        """, (user["patient_id"],)).fetchall()

    return [dict(row) for row in rows]
