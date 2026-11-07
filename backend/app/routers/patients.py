import sqlite3
from contextlib import closing
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core.database import get_db
from app.schemas.patients import PatientCreate

router = APIRouter(tags=["Patients"])


@router.post("/patients", status_code=201)
def create_patient(patient: PatientCreate):
    patient_id = str(uuid4())

    with closing(get_db()) as conn:
        try:
            conn.execute("""
                INSERT INTO patients
                (patient_id, full_name, email, phone)
                VALUES (?, ?, ?, ?)
            """, (
                patient_id,
                patient.full_name,
                str(patient.email),
                patient.phone
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="Patient email already exists"
            )

    return {
        "patient_id": patient_id,
        "full_name": patient.full_name,
        "email": str(patient.email),
        "phone": patient.phone
    }


@router.get("/patients")
def list_patients():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT patient_id, full_name, email, phone
            FROM patients
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]
