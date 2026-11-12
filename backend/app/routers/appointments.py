
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

ALLOWED_ORIGINS = {
    "https://hospital-platform-mu.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:5174",
}


# ------------------------------------------
# AUTHENTICATION AND AUTHORIZATION
# ------------------------------------------

def check_request_origin(request: Request):
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

    if (
        user["role"] != "patient"
        or not user["patient_id"]
    ):
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


class PatientBookingCreate(BaseModel):
    doctor_id: str
    slot_id: str


# ------------------------------------------
# TIME HELPERS
# ------------------------------------------

def parse_utc(value):
    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def times_overlap(
    first_start,
    first_end,
    second_start,
    second_end,
):
    return (
        first_start < second_end
        and first_end > second_start
    )


# ------------------------------------------
# BLOCKED SLOT VALIDATION
# ------------------------------------------

def verify_slot_not_blocked(conn, slot_id: str):
    """
    Prevent using a slot blocked by a doctor.

    Must run inside the booking/reschedule
    transaction.

    Requires doctor_slot_blocks migration.
    """
    blocked = conn.execute("""
        SELECT 1
        FROM doctor_slot_blocks
        WHERE slot_id = ?
    """, (slot_id,)).fetchone()

    if blocked is not None:
        raise HTTPException(
            status_code=409,
            detail="This appointment slot is blocked",
        )


# ------------------------------------------
# PATIENT OWNERSHIP
# ------------------------------------------

def verify_appointment_owner(
    conn,
    appointment_id: str,
    patient_id: str,
):
    appointment = conn.execute("""
        SELECT
            appointment_id,
            patient_id,
            doctor_id,
            slot_id,
            status
        FROM appointments
        WHERE appointment_id = ?
          AND patient_id = ?
    """, (
        appointment_id,
        patient_id,
    )).fetchone()

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    return appointment


# ------------------------------------------
# BOOKING CONFLICT VALIDATION
# ------------------------------------------

def verify_no_booking_conflicts(
    conn,
    patient_id: str,
    doctor_id: str,
    start_time,
    end_time,
    exclude_appointment_id: str | None = None,
):
    """
    Must be called inside BEGIN IMMEDIATE.

    Prevents overlapping patient appointments
    and overlapping doctor appointments.
    """
    if end_time <= start_time:
        raise HTTPException(
            status_code=409,
            detail="Invalid appointment time range",
        )

    if start_time <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail="Cannot book a past slot",
        )

    rows = conn.execute("""
        SELECT
            a.appointment_id,
            a.patient_id,
            a.doctor_id,
            s.starts_at,
            s.ends_at
        FROM appointments a
        JOIN doctor_slots s
          ON a.slot_id = s.slot_id
        WHERE a.status IN ('booked', 'completed')
          AND (
              a.patient_id = ?
              OR a.doctor_id = ?
          )
    """, (
        patient_id,
        doctor_id,
    )).fetchall()

    for existing in rows:
        if (
            exclude_appointment_id is not None
            and existing["appointment_id"]
                == exclude_appointment_id
        ):
            continue

        existing_start = parse_utc(
            existing["starts_at"]
        )
        existing_end = parse_utc(
            existing["ends_at"]
        )

        if not times_overlap(
            start_time,
            end_time,
            existing_start,
            existing_end,
        ):
            continue

        if existing["patient_id"] == patient_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "You already have an appointment "
                    "during this time"
                ),
            )

        if existing["doctor_id"] == doctor_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Doctor already has an appointment "
                    "during this time"
                ),
            )


# ------------------------------------------
# CREATE BOOKING
# ------------------------------------------

def create_booking(
    patient_id: str,
    doctor_id: str,
    slot_id: str,
):
    appointment_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        patient = conn.execute("""
            SELECT 1
            FROM patients
            WHERE patient_id = ?
        """, (patient_id,)).fetchone()

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="Patient not found",
            )

        slot = conn.execute("""
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d
              ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            slot_id,
            doctor_id,
        )).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=404,
                detail="Doctor slot not found",
            )

        verify_slot_not_blocked(conn, slot_id)

        start_time = parse_utc(slot["starts_at"])
        end_time = parse_utc(slot["ends_at"])

        verify_no_booking_conflicts(
            conn=conn,
            patient_id=patient_id,
            doctor_id=doctor_id,
            start_time=start_time,
            end_time=end_time,
        )

        try:
            conn.execute("""
                INSERT INTO appointments (
                    appointment_id,
                    patient_id,
                    doctor_id,
                    slot_id
                )
                VALUES (?, ?, ?, ?)
            """, (
                appointment_id,
                patient_id,
                doctor_id,
                slot_id,
            ))

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


# ------------------------------------------
# CANCEL BOOKING
# ------------------------------------------

def cancel_booking(
    appointment_id: str,
    patient_id: str | None = None,
):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        if patient_id is not None:
            appointment = verify_appointment_owner(
                conn,
                appointment_id,
                patient_id,
            )
        else:
            appointment = conn.execute("""
                SELECT appointment_id, status
                FROM appointments
                WHERE appointment_id = ?
            """, (appointment_id,)).fetchone()

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
            cursor = conn.execute("""
                UPDATE appointments
                SET status = 'cancelled'
                WHERE appointment_id = ?
                  AND patient_id = ?
                  AND status = 'booked'
            """, (
                appointment_id,
                patient_id,
            ))
        else:
            cursor = conn.execute("""
                UPDATE appointments
                SET status = 'cancelled'
                WHERE appointment_id = ?
                  AND status = 'booked'
            """, (appointment_id,))

        if cursor.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Unable to cancel appointment",
            )

        # Older test fixtures may not yet contain
        # the reschedule_requests table.
        has_request_table = conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'reschedule_requests'
        """).fetchone()

        if has_request_table:
            conn.execute("""
                UPDATE reschedule_requests
                SET
                    status = 'cancelled',
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
        "status": "cancelled",
        "message": "Appointment cancelled successfully",
    }


# ------------------------------------------
# RESCHEDULE BOOKING
# ADMIN USE; PATIENT DIRECT ROUTE DISABLED
# ------------------------------------------

def reschedule_booking(
    appointment_id: str,
    new_slot_id: str,
    patient_id: str | None = None,
):
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        if patient_id is not None:
            appointment = verify_appointment_owner(
                conn,
                appointment_id,
                patient_id,
            )
        else:
            appointment = conn.execute("""
                SELECT
                    appointment_id,
                    patient_id,
                    doctor_id,
                    slot_id,
                    status
                FROM appointments
                WHERE appointment_id = ?
            """, (appointment_id,)).fetchone()

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

        new_slot = conn.execute("""
            SELECT
                s.slot_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d
              ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            new_slot_id,
            appointment["doctor_id"],
        )).fetchone()

        if new_slot is None:
            raise HTTPException(
                status_code=404,
                detail="New doctor slot not found",
            )

        verify_slot_not_blocked(conn, new_slot_id)

        start_time = parse_utc(new_slot["starts_at"])
        end_time = parse_utc(new_slot["ends_at"])

        verify_no_booking_conflicts(
            conn=conn,
            patient_id=appointment["patient_id"],
            doctor_id=appointment["doctor_id"],
            start_time=start_time,
            end_time=end_time,
            exclude_appointment_id=appointment_id,
        )

        try:
            if patient_id is not None:
                cursor = conn.execute("""
                    UPDATE appointments
                    SET slot_id = ?
                    WHERE appointment_id = ?
                      AND patient_id = ?
                      AND status = 'booked'
                """, (
                    new_slot_id,
                    appointment_id,
                    patient_id,
                ))
            else:
                cursor = conn.execute("""
                    UPDATE appointments
                    SET slot_id = ?
                    WHERE appointment_id = ?
                      AND status = 'booked'
                """, (
                    new_slot_id,
                    appointment_id,
                ))

            if cursor.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="Unable to reschedule appointment",
                )

            # An admin reschedule makes any pending
            # doctor approval request obsolete.
            has_request_table = conn.execute("""
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'reschedule_requests'
            """).fetchone()

            if has_request_table:
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


# ------------------------------------------
# ADMIN ROUTES
# ------------------------------------------

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
            JOIN patients p
              ON a.patient_id = p.patient_id
            JOIN doctors d
              ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s
              ON a.slot_id = s.slot_id
            ORDER BY s.starts_at
        """).fetchall()

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


# ------------------------------------------
# PATIENT ROUTES
# ------------------------------------------

@router.get("/my/appointments")
def my_appointments(
    user=Depends(require_patient),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.doctor_id,
                a.slot_id,
                a.status,
                d.full_name AS doctor,
                d.full_name AS doctor_name,
                d.specialization,
                d.department,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN doctors d
              ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s
              ON a.slot_id = s.slot_id
            WHERE a.patient_id = ?
            ORDER BY s.starts_at
        """, (user["patient_id"],)).fetchall()

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
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        verify_appointment_owner(
            conn,
            appointment_id,
            user["patient_id"],
        )

    raise HTTPException(
        status_code=409,
        detail=(
            "Direct rescheduling is disabled. "
            "Submit a reschedule request for doctor approval."
        ),
    )
