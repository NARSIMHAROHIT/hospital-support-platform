
import sqlite3
from contextlib import closing
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.database import get_db
from app.core.permissions import require_admin, require_patient
from app.schemas.patients import PatientCreate

router = APIRouter(tags=["Patients"])

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


# Admin creates a patient
@router.post("/patients", status_code=201)
def create_patient(
    patient: PatientCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
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
                patient.phone,
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="Patient email already exists",
            )

    return {
        "patient_id": patient_id,
        "full_name": patient.full_name,
        "email": str(patient.email),
        "phone": patient.phone,
    }


# Admin sees all patients
@router.get("/patients")
def list_patients(admin=Depends(require_admin)):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT patient_id, full_name, email, phone
            FROM patients
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]


# Logged-in patient sees only their own profile
@router.get("/my/profile")
def my_profile(user=Depends(require_patient)):
    with closing(get_db()) as conn:
        patient = conn.execute("""
            SELECT patient_id, full_name, email, phone, created_at
            FROM patients
            WHERE patient_id = ?
        """, (user["patient_id"],)).fetchone()

    if patient is None:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not found",
        )

    return dict(patient)
