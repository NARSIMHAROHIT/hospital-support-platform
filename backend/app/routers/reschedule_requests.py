
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel

from app.core.database import get_db
from app.routers.appointments import (
    check_request_origin,
    parse_utc,
    require_patient,
    verify_appointment_owner,
    verify_no_booking_conflicts,
    verify_slot_not_blocked,
)

router = APIRouter(tags=["Reschedule Requests"])


class RescheduleRequestCreate(BaseModel):
    requested_slot_id: str


# ------------------------------------------
# CREATE PATIENT RESCHEDULE REQUEST
# ------------------------------------------

@router.post(
    "/my/appointments/{appointment_id}/reschedule-requests",
    status_code=201,
)
def request_reschedule(
    appointment_id: str,
    payload: RescheduleRequestCreate,
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    patient_id = user["patient_id"]
    request_id = str(uuid4())
    now = datetime.now(timezone.utc)

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        appointment = verify_appointment_owner(
            conn,
            appointment_id,
            patient_id,
        )

        if appointment["status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Only booked appointments can be rescheduled",
            )

        original_slot = conn.execute("""
            SELECT starts_at
            FROM doctor_slots
            WHERE slot_id = ?
              AND doctor_id = ?
        """, (
            appointment["slot_id"],
            appointment["doctor_id"],
        )).fetchone()

        if (
            original_slot is None
            or parse_utc(original_slot["starts_at"]) <= now
        ):
            raise HTTPException(
                status_code=409,
                detail="Cannot reschedule a past appointment",
            )

        if (
            appointment["slot_id"]
            == payload.requested_slot_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Choose a different appointment slot",
            )

        pending = conn.execute("""
            SELECT request_id
            FROM reschedule_requests
            WHERE appointment_id = ?
              AND status = 'pending'
        """, (appointment_id,)).fetchone()

        if pending is not None:
            raise HTTPException(
                status_code=409,
                detail="A reschedule request is already pending",
            )

        slot = conn.execute("""
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d
              ON d.doctor_id = s.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            payload.requested_slot_id,
            appointment["doctor_id"],
        )).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=404,
                detail="Requested doctor slot not found",
            )

        # Doctor may have blocked this slot.
        verify_slot_not_blocked(
            conn,
            payload.requested_slot_id,
        )

        start_time = parse_utc(slot["starts_at"])
        end_time = parse_utc(slot["ends_at"])

        verify_no_booking_conflicts(
            conn=conn,
            patient_id=patient_id,
            doctor_id=appointment["doctor_id"],
            start_time=start_time,
            end_time=end_time,
            exclude_appointment_id=appointment_id,
        )

        try:
            conn.execute("""
                INSERT INTO reschedule_requests (
                    request_id,
                    appointment_id,
                    patient_id,
                    doctor_id,
                    original_slot_id,
                    requested_slot_id,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (
                request_id,
                appointment_id,
                patient_id,
                appointment["doctor_id"],
                appointment["slot_id"],
                payload.requested_slot_id,
                now.isoformat(),
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Unable to create reschedule request",
            )

    return {
        "request_id": request_id,
        "appointment_id": appointment_id,
        "requested_slot_id": payload.requested_slot_id,
        "status": "pending",
        "message": "Request submitted for doctor review",
    }


# ------------------------------------------
# VIEW PATIENT RESCHEDULE REQUEST HISTORY
# ------------------------------------------

@router.get("/my/reschedule-requests")
def list_my_reschedule_requests(
    user=Depends(require_patient),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                r.request_id,
                r.appointment_id,
                r.status,
                r.created_at,
                r.decided_at,
                d.full_name AS doctor,
                original.starts_at AS original_starts_at,
                original.ends_at AS original_ends_at,
                requested.starts_at AS requested_starts_at,
                requested.ends_at AS requested_ends_at
            FROM reschedule_requests r
            JOIN doctors d
              ON d.doctor_id = r.doctor_id
            JOIN doctor_slots original
              ON original.slot_id = r.original_slot_id
            JOIN doctor_slots requested
              ON requested.slot_id = r.requested_slot_id
            WHERE r.patient_id = ?
            ORDER BY r.created_at DESC
        """, (user["patient_id"],)).fetchall()

    return [dict(row) for row in rows]
