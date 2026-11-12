
from contextlib import closing

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
)

from app.core.database import get_db
from app.routers import clinical_patients


router = APIRouter(
    prefix="/my/clinical-notes",
    tags=["Patient Clinical Notes"],
)


def require_patient_session(
    hospital_session: str | None = Cookie(default=None),
):
    if not hospital_session:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    user = clinical_patients.get_current_user(
        hospital_session
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    if (
        user.get("role") != "patient"
        or not user.get("patient_id")
    ):
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    return user


@router.get("")
def list_my_released_notes(
    user: dict = Depends(require_patient_session),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                n.note_id,
                n.appointment_id,
                n.observations,
                n.assessment,
                n.treatment_plan,
                n.signed_at,
                r.released_at
            FROM doctor_clinical_notes n
            JOIN patient_note_releases r
              ON r.note_id = n.note_id
            WHERE n.patient_id = ?
              AND n.status = 'signed'
            ORDER BY r.released_at DESC, n.note_id DESC
        """, (
            user["patient_id"],
        )).fetchall()

    return {
        "total": len(rows),
        "notes": [dict(row) for row in rows],
    }


@router.get("/{note_id}")
def get_my_released_note(
    note_id: str,
    user: dict = Depends(require_patient_session),
):
    with closing(get_db()) as conn:
        note = conn.execute("""
            SELECT
                n.note_id,
                n.appointment_id,
                n.observations,
                n.assessment,
                n.treatment_plan,
                n.signed_at,
                r.released_at
            FROM doctor_clinical_notes n
            JOIN patient_note_releases r
              ON r.note_id = n.note_id
            WHERE n.note_id = ?
              AND n.patient_id = ?
              AND n.status = 'signed'
        """, (
            note_id,
            user["patient_id"],
        )).fetchone()

    if note is None:
        raise HTTPException(
            status_code=404,
            detail="Released clinical note not found",
        )

    return dict(note)
