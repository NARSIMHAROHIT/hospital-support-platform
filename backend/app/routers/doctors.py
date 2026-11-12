
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.database import get_db
from app.core.permissions import require_admin
from app.routers.appointments import parse_utc, times_overlap
from app.schemas.doctors import DoctorCreate, AvailabilityCreate

router = APIRouter(tags=["Doctors"])

ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


def check_request_origin(request: Request):
    origin = request.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Request origin not allowed",
        )


@router.post("/doctors", status_code=201)
def create_doctor(
    doctor: DoctorCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    doctor_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("""
            INSERT INTO doctors
                (doctor_id, full_name, specialization, department)
            VALUES (?, ?, ?, ?)
        """, (
            doctor_id,
            doctor.full_name,
            doctor.specialization,
            doctor.department,
        ))
        conn.commit()

    return {
        "doctor_id": doctor_id,
        "full_name": doctor.full_name,
        "specialization": doctor.specialization,
        "department": doctor.department,
        "is_active": True,
    }


@router.get("/doctors")
def list_doctors():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT doctor_id, full_name, specialization, department
            FROM doctors
            WHERE is_active = 1
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]


@router.post("/doctors/{doctor_id}/slots", status_code=201)
def create_doctor_slot(
    doctor_id: str,
    slot: AvailabilityCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    if (
        slot.starts_at.utcoffset() is None
        or slot.ends_at.utcoffset() is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Timezone offset required",
        )

    start = slot.starts_at.astimezone(timezone.utc)
    end = slot.ends_at.astimezone(timezone.utc)

    if end <= start:
        raise HTTPException(
            status_code=422,
            detail="Invalid time range",
        )

    if start <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail="Cannot create a slot in the past",
        )

    slot_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        doctor = conn.execute("""
            SELECT 1
            FROM doctors
            WHERE doctor_id = ?
              AND is_active = 1
        """, (doctor_id,)).fetchone()

        if doctor is None:
            raise HTTPException(
                status_code=404,
                detail="Active doctor not found",
            )

        existing_slots = conn.execute("""
            SELECT starts_at, ends_at
            FROM doctor_slots
            WHERE doctor_id = ?
        """, (doctor_id,)).fetchall()

        for existing in existing_slots:
            if times_overlap(
                start,
                end,
                parse_utc(existing["starts_at"]),
                parse_utc(existing["ends_at"]),
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Slot overlaps existing schedule",
                )

        conn.execute("""
            INSERT INTO doctor_slots
                (slot_id, doctor_id, starts_at, ends_at)
            VALUES (?, ?, ?, ?)
        """, (
            slot_id,
            doctor_id,
            start.isoformat(),
            end.isoformat(),
        ))
        conn.commit()

    return {
        "slot_id": slot_id,
        "doctor_id": doctor_id,
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
    }


@router.get("/doctors/{doctor_id}/slots")
def get_available_slots(doctor_id: str):
    now = datetime.now(timezone.utc)

    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                s.slot_id,
                s.doctor_id,
                s.starts_at,
                s.ends_at
            FROM doctor_slots s
            JOIN doctors d
              ON s.doctor_id = d.doctor_id
            WHERE s.doctor_id = ?
              AND d.is_active = 1
              AND NOT EXISTS (
                  SELECT 1
                  FROM doctor_slot_blocks b
                  WHERE b.slot_id = s.slot_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM appointments a
                  WHERE a.slot_id = s.slot_id
                    AND a.status IN ('booked', 'completed')
              )
            ORDER BY s.starts_at
        """, (doctor_id,)).fetchall()

    # Remove expired slots even if they remain in the database.
    return [
        dict(row)
        for row in rows
        if parse_utc(row["starts_at"]) > now
    ]
