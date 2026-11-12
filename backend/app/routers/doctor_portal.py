
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException

from app.core.database import get_db
from app.core.security import get_current_user
from app.routers.appointments import (
    check_request_origin,
    parse_utc,
    verify_no_booking_conflicts,
    verify_slot_not_blocked,
)

router = APIRouter(
    prefix="/doctor",
    tags=["Doctor Portal"],
)


def require_doctor(
    hospital_session: str | None = Cookie(default=None),
):
    user = get_current_user(hospital_session)

    if user["role"] != "doctor" or not user.get("doctor_id"):
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    return user


@router.get("/me")
def doctor_profile(user=Depends(require_doctor)):
    with closing(get_db()) as conn:
        doctor = conn.execute("""
            SELECT
                doctor_id,
                full_name,
                specialization,
                department
            FROM doctors
            WHERE doctor_id = ?
              AND is_active = 1
        """, (user["doctor_id"],)).fetchone()

    if doctor is None:
        raise HTTPException(
            status_code=403,
            detail="Doctor account is inactive",
        )

    return {
        **dict(doctor),
        "email": user["email"],
    }


@router.get("/appointments")
def doctor_appointments(user=Depends(require_doctor)):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.status,
                p.full_name AS patient_name,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN patients p
              ON p.patient_id = a.patient_id
            JOIN doctor_slots s
              ON s.slot_id = a.slot_id
            WHERE a.doctor_id = ?
            ORDER BY s.starts_at DESC
        """, (user["doctor_id"],)).fetchall()

    return [dict(row) for row in rows]


@router.get("/schedule")
def doctor_schedule(user=Depends(require_doctor)):
    """
    Return every slot belonging to this doctor.

    The database determines whether a slot
    is occupied, blocked, or available.
    """
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM appointments a
                        WHERE a.slot_id = s.slot_id
                          AND a.doctor_id = s.doctor_id
                          AND a.status IN ('booked', 'completed')
                    )
                    THEN 'occupied'

                    WHEN EXISTS (
                        SELECT 1
                        FROM doctor_slot_blocks b
                        WHERE b.slot_id = s.slot_id
                    )
                    THEN 'blocked'

                    ELSE 'available'
                END AS availability
            FROM doctor_slots s
            WHERE s.doctor_id = ?
            ORDER BY s.starts_at
        """, (user["doctor_id"],)).fetchall()

    return [dict(row) for row in rows]


@router.get("/reschedule-requests")
def doctor_reschedule_requests(user=Depends(require_doctor)):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                r.request_id,
                r.appointment_id,
                r.status,
                r.created_at,
                r.decided_at,
                p.full_name AS patient_name,
                original.starts_at AS original_starts_at,
                original.ends_at AS original_ends_at,
                requested.starts_at AS requested_starts_at,
                requested.ends_at AS requested_ends_at
            FROM reschedule_requests r
            JOIN appointments a
              ON a.appointment_id = r.appointment_id
            JOIN patients p
              ON p.patient_id = r.patient_id
            JOIN doctor_slots original
              ON original.slot_id = r.original_slot_id
            JOIN doctor_slots requested
              ON requested.slot_id = r.requested_slot_id
            WHERE r.doctor_id = ?
              AND a.doctor_id = r.doctor_id
              AND a.patient_id = r.patient_id
            ORDER BY
                CASE
                    WHEN r.status = 'pending' THEN 0
                    ELSE 1
                END,
                r.created_at DESC
        """, (user["doctor_id"],)).fetchall()

    return [dict(row) for row in rows]


def get_pending_request(conn, request_id, doctor_id):
    request = conn.execute("""
        SELECT
            r.request_id,
            r.appointment_id,
            r.patient_id,
            r.doctor_id,
            r.original_slot_id,
            r.requested_slot_id,
            r.status AS request_status,
            a.status AS appointment_status,
            a.slot_id AS current_slot_id
        FROM reschedule_requests r
        JOIN appointments a
          ON a.appointment_id = r.appointment_id
        WHERE r.request_id = ?
          AND r.doctor_id = ?
          AND a.doctor_id = ?
          AND a.patient_id = r.patient_id
    """, (
        request_id,
        doctor_id,
        doctor_id,
    )).fetchone()

    if request is None:
        raise HTTPException(
            status_code=404,
            detail="Reschedule request not found",
        )

    if request["request_status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail="Request has already been processed",
        )

    return request


@router.patch("/reschedule-requests/{request_id}/approve")
def approve_reschedule(
    request_id: str,
    user=Depends(require_doctor),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        request = get_pending_request(
            conn,
            request_id,
            user["doctor_id"],
        )

        if request["appointment_status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Original appointment is no longer booked",
            )

        if request["current_slot_id"] != request["original_slot_id"]:
            raise HTTPException(
                status_code=409,
                detail="Original appointment has changed",
            )

        original = conn.execute("""
            SELECT starts_at
            FROM doctor_slots
            WHERE slot_id = ?
              AND doctor_id = ?
        """, (
            request["original_slot_id"],
            user["doctor_id"],
        )).fetchone()

        if (
            original is None
            or parse_utc(original["starts_at"])
            <= datetime.now(timezone.utc)
        ):
            raise HTTPException(
                status_code=409,
                detail="Original appointment has already started",
            )

        slot = conn.execute("""
            SELECT s.starts_at, s.ends_at
            FROM doctor_slots s
            JOIN doctors d
              ON d.doctor_id = s.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            request["requested_slot_id"],
            user["doctor_id"],
        )).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=409,
                detail="Requested slot is no longer available",
            )

        # Newly added: doctor cannot approve a blocked time.
        verify_slot_not_blocked(
            conn,
            request["requested_slot_id"],
        )

        verify_no_booking_conflicts(
            conn=conn,
            patient_id=request["patient_id"],
            doctor_id=user["doctor_id"],
            start_time=parse_utc(slot["starts_at"]),
            end_time=parse_utc(slot["ends_at"]),
            exclude_appointment_id=request["appointment_id"],
        )

        try:
            updated = conn.execute("""
                UPDATE appointments
                SET slot_id = ?
                WHERE appointment_id = ?
                  AND doctor_id = ?
                  AND slot_id = ?
                  AND status = 'booked'
            """, (
                request["requested_slot_id"],
                request["appointment_id"],
                user["doctor_id"],
                request["original_slot_id"],
            ))

            if updated.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Appointment could not be updated",
                )

            now = datetime.now(timezone.utc).isoformat()

            decided = conn.execute("""
                UPDATE reschedule_requests
                SET status = 'approved',
                    decided_at = ?
                WHERE request_id = ?
                  AND doctor_id = ?
                  AND status = 'pending'
            """, (
                now,
                request_id,
                user["doctor_id"],
            ))

            if decided.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Request could not be approved",
                )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Requested slot is unavailable",
            )

    return {
        "request_id": request_id,
        "status": "approved",
        "message": "Appointment rescheduled successfully",
    }


@router.patch("/reschedule-requests/{request_id}/reject")
def reject_reschedule(
    request_id: str,
    user=Depends(require_doctor),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        request = get_pending_request(
            conn,
            request_id,
            user["doctor_id"],
        )

        if request["appointment_status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Original appointment is no longer booked",
            )

        if request["current_slot_id"] != request["original_slot_id"]:
            raise HTTPException(
                status_code=409,
                detail="Original appointment has changed",
            )

        updated = conn.execute("""
            UPDATE reschedule_requests
            SET status = 'rejected',
                decided_at = ?
            WHERE request_id = ?
              AND doctor_id = ?
              AND status = 'pending'
        """, (
            datetime.now(timezone.utc).isoformat(),
            request_id,
            user["doctor_id"],
        ))

        if updated.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Request could not be rejected",
            )

        conn.commit()

    return {
        "request_id": request_id,
        "status": "rejected",
        "message": "Request rejected; original appointment unchanged",
    }
