
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import get_db
from app.routers.appointments import (
    check_request_origin,
    parse_utc,
    times_overlap,
)
from app.routers.doctor_portal import require_doctor


router = APIRouter(
    prefix="/doctor/schedule",
    tags=["Doctor Schedule Management"],
)


class SlotCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime


def ensure_schedule_tables(conn):
    """
    Required local development schema.

    The same SQL should later be added to the
    project's versioned migration system.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doctor_slot_blocks (
            slot_id TEXT PRIMARY KEY,
            blocked_at TEXT NOT NULL,
            FOREIGN KEY (slot_id)
                REFERENCES doctor_slots(slot_id)
        )
    """)


@router.post("/slots", status_code=201)
def create_slot(
    payload: SlotCreate,
    user=Depends(require_doctor),
    _origin=Depends(check_request_origin),
):
    doctor_id = user["doctor_id"]

    # Explicit timezone offsets are required.
    if (
        payload.starts_at.tzinfo is None
        or payload.ends_at.tzinfo is None
        or payload.starts_at.utcoffset() is None
        or payload.ends_at.utcoffset() is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Appointment times must include a timezone offset",
        )

    start = payload.starts_at.astimezone(timezone.utc)
    end = payload.ends_at.astimezone(timezone.utc)

    duration_minutes = (end - start).total_seconds() / 60

    if start <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail="Cannot create a slot in the past",
        )

    if not 15 <= duration_minutes <= 120:
        raise HTTPException(
            status_code=422,
            detail="Slot duration must be between 15 and 120 minutes",
        )

    slot_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        doctor = conn.execute("""
            SELECT doctor_id
            FROM doctors
            WHERE doctor_id = ?
              AND is_active = 1
        """, (doctor_id,)).fetchone()

        if doctor is None:
            raise HTTPException(
                status_code=403,
                detail="Doctor account is inactive",
            )

        existing_slots = conn.execute("""
            SELECT starts_at, ends_at
            FROM doctor_slots
            WHERE doctor_id = ?
        """, (doctor_id,)).fetchall()

        for slot in existing_slots:
            if times_overlap(
                start,
                end,
                parse_utc(slot["starts_at"]),
                parse_utc(slot["ends_at"]),
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Slot overlaps an existing doctor schedule",
                )

        try:
            conn.execute("""
                INSERT INTO doctor_slots (
                    slot_id,
                    doctor_id,
                    starts_at,
                    ends_at
                )
                VALUES (?, ?, ?, ?)
            """, (
                slot_id,
                doctor_id,
                start.isoformat(),
                end.isoformat(),
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Unable to create appointment slot",
            )

    return {
        "slot_id": slot_id,
        "doctor_id": doctor_id,
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "availability": "available",
    }


@router.patch("/slots/{slot_id}/block")
def block_slot(
    slot_id: str,
    user=Depends(require_doctor),
    _origin=Depends(check_request_origin),
):
    doctor_id = user["doctor_id"]

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        ensure_schedule_tables(conn)

        slot = conn.execute("""
            SELECT slot_id, starts_at, ends_at
            FROM doctor_slots
            WHERE slot_id = ?
              AND doctor_id = ?
        """, (slot_id, doctor_id)).fetchone()

        if slot is None:
            raise HTTPException(
                status_code=404,
                detail="Doctor slot not found",
            )

        start = parse_utc(slot["starts_at"])
        end = parse_utc(slot["ends_at"])

        if start <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=409,
                detail="Cannot block a slot that has already started",
            )

        # Check every overlapping appointment for this doctor,
        # including bookings created using another slot ID.
        appointments = conn.execute("""
            SELECT s.starts_at, s.ends_at
            FROM appointments a
            JOIN doctor_slots s ON s.slot_id = a.slot_id
            WHERE a.doctor_id = ?
              AND a.status IN ('booked', 'completed')
        """, (doctor_id,)).fetchall()

        for appointment in appointments:
            if times_overlap(
                start,
                end,
                parse_utc(appointment["starts_at"]),
                parse_utc(appointment["ends_at"]),
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cannot block a slot with a booked appointment",
                )

        existing = conn.execute("""
            SELECT 1
            FROM doctor_slot_blocks
            WHERE slot_id = ?
        """, (slot_id,)).fetchone()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Slot is already blocked",
            )

        conn.execute("""
            INSERT INTO doctor_slot_blocks (
                slot_id,
                blocked_at
            )
            VALUES (?, ?)
        """, (
            slot_id,
            datetime.now(timezone.utc).isoformat(),
        ))

        conn.commit()

    return {
        "slot_id": slot_id,
        "availability": "blocked",
        "message": "Slot blocked successfully",
    }
