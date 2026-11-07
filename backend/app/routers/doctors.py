
from contextlib import closing
from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core.database import get_db
from app.schemas.doctors import DoctorCreate, AvailabilityCreate

router = APIRouter(tags=["Doctors"])


@router.post("/doctors", status_code=201)
def create_doctor(doctor: DoctorCreate):
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
            doctor.department
        ))
        conn.commit()

    return {
        "doctor_id": doctor_id,
        "full_name": doctor.full_name,
        "specialization": doctor.specialization,
        "department": doctor.department,
        "is_active": True
    }


@router.get("/doctors")
def list_doctors():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM doctors
            WHERE is_active = 1
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]


@router.post("/doctors/{doctor_id}/slots", status_code=201)
def create_doctor_slot(
    doctor_id: str,
    slot: AvailabilityCreate
):
    if (
        slot.starts_at.utcoffset() is None
        or slot.ends_at.utcoffset() is None
    ):
        raise HTTPException(422, "Timezone offset required")

    if slot.ends_at <= slot.starts_at:
        raise HTTPException(422, "Invalid time range")

    start = slot.starts_at.astimezone(timezone.utc).isoformat()
    end = slot.ends_at.astimezone(timezone.utc).isoformat()
    slot_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        doctor = conn.execute("""
            SELECT 1
            FROM doctors
            WHERE doctor_id = ? AND is_active = 1
        """, (doctor_id,)).fetchone()

        if doctor is None:
            raise HTTPException(404, "Active doctor not found")

        overlap = conn.execute("""
            SELECT 1
            FROM doctor_slots
            WHERE doctor_id = ?
              AND starts_at < ?
              AND ends_at > ?
        """, (doctor_id, end, start)).fetchone()

        if overlap:
            raise HTTPException(
                409, "Slot overlaps existing schedule"
            )

        conn.execute("""
            INSERT INTO doctor_slots
            (slot_id, doctor_id, starts_at, ends_at)
            VALUES (?, ?, ?, ?)
        """, (slot_id, doctor_id, start, end))

        conn.commit()

    return {
        "slot_id": slot_id,
        "doctor_id": doctor_id,
        "starts_at": start,
        "ends_at": end
    }


@router.get("/doctors/{doctor_id}/slots")
def get_available_slots(doctor_id: str):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT s.*
            FROM doctor_slots s
            WHERE s.doctor_id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM appointments a
                  WHERE a.slot_id = s.slot_id
                    AND a.status IN ('booked', 'completed')
              )
            ORDER BY s.starts_at
        """, (doctor_id,)).fetchall()

    return [dict(row) for row in rows]
