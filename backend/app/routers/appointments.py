
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
)
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.appointments import (
    AppointmentCreate,
    AppointmentReschedule,
)


router = APIRouter(tags=["Appointments"])


# Local development only.
ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


# ==================================================
# 1. SECURITY HELPERS
# ==================================================

def check_request_origin(request: Request):
    """
    Basic CSRF safeguard for cookie-authenticated
    state-changing requests during local development.
    """
    origin = request.headers.get("origin")

    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Request origin not allowed",
        )


def require_patient(
    hospital_session: str | None = Cookie(default=None),
):
    user = get_current_user(hospital_session)

    if user["role"] != "patient" or not user["patient_id"]:
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    return user


def require_admin(
    hospital_session: str | None = Cookie(default=None),
):
    user = get_current_user(hospital_session)

    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    return user


def verify_appointment_owner(
    conn,
    appointment_id: str,
    patient_id: str,
):
    appointment = conn.execute(
        """
        SELECT
            appointment_id,
            patient_id,
            doctor_id,
            slot_id,
            status
        FROM appointments
        WHERE appointment_id = ?
          AND patient_id = ?
        """,
        (appointment_id, patient_id),
    ).fetchone()

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    return appointment


# ==================================================
# 2. REQUEST SCHEMA
# ==================================================

class PatientBookingCreate(BaseModel):
    doctor_id: str
    slot_id: str


# ==================================================
# 3. SHARED APPOINTMENT OPERATIONS
# ==================================================

def create_booking(
    patient_id: str,
    doctor_id: str,
    slot_id: str,
):
    """
    Create a booking for an authorized patient ID.
    Uses a transaction to prevent double booking.
    """
    appointment_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        patient = conn.execute(
            """
            SELECT 1
            FROM patients
            WHERE patient_id = ?
            """,
            (patient_id,),
        ).fetchone()

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="Patient not found",
            )

        slot = conn.execute(
            """
            SELECT s.slot_id, s.starts_at
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
            """,
            (slot_id, doctor_id),
        ).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=404,
                detail="Doctor slot not found",
            )

        start_time = datetime.fromisoformat(
            slot["starts_at"]
        )

        if start_time <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=409,
                detail="Cannot book a past slot",
            )

        try:
            conn.execute(
                """
                INSERT INTO appointments
                (
                    appointment_id,
                    patient_id,
                    doctor_id,
                    slot_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    appointment_id,
                    patient_id,
                    doctor_id,
                    slot_id,
                ),
            )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Slot already booked",
            )

    return {
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "slot_id": slot_id,
        "status": "booked",
    }


def cancel_booking(
    appointment_id: str,
    patient_id: str | None = None,
):
    """
    patient_id provided: check appointment ownership.
    patient_id omitted: intended for admin-only route.
    """
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        if patient_id is not None:
            appointment = verify_appointment_owner(
                conn,
                appointment_id,
                patient_id,
            )
        else:
            appointment = conn.execute(
                """
                SELECT appointment_id, status
                FROM appointments
                WHERE appointment_id = ?
                """,
                (appointment_id,),
            ).fetchone()

            if appointment is None:
                raise HTTPException(
                    status_code=404,
                    detail="Appointment not found",
                )

        if appointment["status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Only booked appointments can be cancelled",
            )

        if patient_id is not None:
            cursor = conn.execute(
                """
                UPDATE appointments
                SET status = 'cancelled'
                WHERE appointment_id = ?
                  AND patient_id = ?
                  AND status = 'booked'
                """,
                (appointment_id, patient_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE appointments
                SET status = 'cancelled'
                WHERE appointment_id = ?
                  AND status = 'booked'
                """,
                (appointment_id,),
            )

        if cursor.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Unable to cancel appointment",
            )

        conn.commit()

    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "message": "Appointment cancelled successfully",
    }


def reschedule_booking(
    appointment_id: str,
    new_slot_id: str,
    patient_id: str | None = None,
):
    """
    Reschedules an existing booked appointment.

    Patient routes enforce ownership.
    Admin routes may manage any appointment.
    """
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        if patient_id is not None:
            appointment = verify_appointment_owner(
                conn,
                appointment_id,
                patient_id,
            )
        else:
            appointment = conn.execute(
                """
                SELECT
                    appointment_id,
                    doctor_id,
                    slot_id,
                    status
                FROM appointments
                WHERE appointment_id = ?
                """,
                (appointment_id,),
            ).fetchone()

            if appointment is None:
                raise HTTPException(
                    status_code=404,
                    detail="Appointment not found",
                )

        if appointment["status"] != "booked":
            raise HTTPException(
                status_code=409,
                detail="Only booked appointments can be rescheduled",
            )

        if appointment["slot_id"] == new_slot_id:
            raise HTTPException(
                status_code=409,
                detail="New slot must be different",
            )

        new_slot = conn.execute(
            """
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
            """,
            (
                new_slot_id,
                appointment["doctor_id"],
            ),
        ).fetchone()

        if new_slot is None:
            raise HTTPException(
                status_code=404,
                detail="New doctor slot not found",
            )

        start_time = datetime.fromisoformat(
            new_slot["starts_at"]
        )

        if start_time <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=409,
                detail="Cannot reschedule into a past slot",
            )

        occupied = conn.execute(
            """
            SELECT 1
            FROM appointments
            WHERE slot_id = ?
              AND status IN ('booked', 'completed')
            """,
            (new_slot_id,),
        ).fetchone()

        if occupied:
            raise HTTPException(
                status_code=409,
                detail="Requested slot is unavailable",
            )

        try:
            if patient_id is not None:
                cursor = conn.execute(
                    """
                    UPDATE appointments
                    SET slot_id = ?
                    WHERE appointment_id = ?
                      AND patient_id = ?
                      AND status = 'booked'
                    """,
                    (
                        new_slot_id,
                        appointment_id,
                        patient_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE appointments
                    SET slot_id = ?
                    WHERE appointment_id = ?
                      AND status = 'booked'
                    """,
                    (new_slot_id, appointment_id),
                )

            if cursor.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Unable to reschedule appointment",
                )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Requested slot is unavailable",
            )

    return {
        "appointment_id": appointment_id,
        "status": "booked",
        "previous_slot_id": appointment["slot_id"],
        "new_slot_id": new_slot_id,
        "starts_at": new_slot["starts_at"],
        "ends_at": new_slot["ends_at"],
        "message": "Appointment rescheduled successfully",
    }


# ==================================================
# 4. ADMIN APPOINTMENT ENDPOINTS
# ==================================================

@router.post("/appointments", status_code=201)
def book_appointment(
    booking: AppointmentCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    return create_booking(
        patient_id=booking.patient_id,
        doctor_id=booking.doctor_id,
        slot_id=booking.slot_id,
    )


@router.get("/appointments")
def list_appointments(
    admin=Depends(require_admin),
):
    with closing(get_db()) as conn:
        rows = conn.execute(
            """
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
            """
        ).fetchall()

    return [dict(row) for row in rows]


@router.patch("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: str,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    return cancel_booking(appointment_id)


@router.patch("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: str,
    request: AppointmentReschedule,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    return reschedule_booking(
        appointment_id=appointment_id,
        new_slot_id=request.new_slot_id,
    )


# ==================================================
# 5. PATIENT APPOINTMENT ENDPOINTS
# ==================================================

@router.get("/my/appointments")
def my_appointments(
    user=Depends(require_patient),
):
    with closing(get_db()) as conn:
        rows = conn.execute(
            """
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
            """,
            (user["patient_id"],),
        ).fetchall()

    return [dict(row) for row in rows]


@router.post("/my/appointments", status_code=201)
def book_my_appointment(
    booking: PatientBookingCreate,
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    return create_booking(
        patient_id=user["patient_id"],
        doctor_id=booking.doctor_id,
        slot_id=booking.slot_id,
    )


@router.patch("/my/appointments/{appointment_id}/cancel")
def cancel_my_appointment(
    appointment_id: str,
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    return cancel_booking(
        appointment_id=appointment_id,
        patient_id=user["patient_id"],
    )


@router.patch("/my/appointments/{appointment_id}/reschedule")
def reschedule_my_appointment(
    appointment_id: str,
    request: AppointmentReschedule,
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    return reschedule_booking(
        appointment_id=appointment_id,
        new_slot_id=request.new_slot_id,
        patient_id=user["patient_id"],
    )
