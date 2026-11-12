
from contextlib import closing
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.routers.appointments import (
    check_request_origin,
    parse_utc,
)
from app.routers.doctor_portal import require_doctor


router = APIRouter(
    prefix="/doctor",
    tags=["Doctor Visit Management"],
)


@router.patch("/appointments/{appointment_id}/complete")
def complete_visit(
    appointment_id: str,
    user=Depends(require_doctor),
    _origin=Depends(check_request_origin),
):
    doctor_id = user["doctor_id"]

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        appointment = conn.execute("""
            SELECT
                a.appointment_id,
                a.patient_id,
                a.doctor_id,
                a.status,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN doctor_slots s
              ON s.slot_id = a.slot_id
            WHERE a.appointment_id = ?
              AND a.doctor_id = ?
        """, (
            appointment_id,
            doctor_id,
        )).fetchone()

        if appointment is None:
            raise HTTPException(
                status_code=404,
                detail="Appointment not found",
            )

        if appointment["status"] == "completed":
            raise HTTPException(
                status_code=409,
                detail="Visit already completed",
            )

        if appointment["status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Only booked visits can be completed",
            )

        start_time = parse_utc(
            appointment["starts_at"]
        )

        if start_time > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=409,
                detail="Cannot complete a future appointment",
            )

        updated = conn.execute("""
            UPDATE appointments
            SET status = 'completed'
            WHERE appointment_id = ?
              AND doctor_id = ?
              AND status = 'booked'
        """, (
            appointment_id,
            doctor_id,
        ))

        if updated.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Unable to complete visit",
            )

        # Any pending reschedule is no longer actionable.
        conn.execute("""
            UPDATE reschedule_requests
            SET status = 'cancelled',
                decided_at = ?
            WHERE appointment_id = ?
              AND status = 'pending'
        """, (
            datetime.now(timezone.utc).isoformat(),
            appointment_id,
        ))

        conn.commit()

    return {
        "appointment_id": appointment_id,
        "patient_id": appointment["patient_id"],
        "doctor_id": doctor_id,
        "status": "completed",
        "message": "Visit marked as completed",
    }
