
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from app.core.database import get_db
from app.core.clinical_audit import record_clinical_audit

from app.routers import clinical_patients
from app.routers.appointments import check_request_origin
from app.routers.doctor_documents import (
    require_doctor_documents,
)
from app.routers.doctor_clinical_notes import (
    load_note,
    require_author,
)


router = APIRouter(
    prefix="/clinical/note-sharing",
    tags=["Clinical Note Sharing"],
)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def require_patient_session(request: Request):
    token = request.cookies.get("hospital_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    # Reuse existing patient session validation.
    user = clinical_patients.get_current_user(token)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    if user.get("role") != "patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    # Verify the actual database account.
    with closing(get_db()) as conn:
        account = conn.execute("""
            SELECT patient_id, is_active
            FROM users
            WHERE user_id = ?
              AND role = 'patient'
        """, (
            user["user_id"],
        )).fetchone()

    if (
        account is None
        or not account["is_active"]
        or not account["patient_id"]
        or account["patient_id"] != user.get("patient_id")
    ):
        raise HTTPException(
            status_code=403,
            detail="Active patient account required",
        )

    return user


def write_release_event(
    conn,
    note_id,
    actor_id,
    event_type,
):
    """
    Preserve the existing release/revoke event history.
    """

    conn.execute("""
        INSERT INTO doctor_note_release_events (
            event_id,
            note_id,
            actor_user_id,
            event_type,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        str(uuid4()),
        note_id,
        actor_id,
        event_type,
        now_utc(),
    ))


def fetch_release(conn, note_id):
    return conn.execute("""
        SELECT
            note_id,
            released_by_user_id,
            released_at,
            revoked_at,
            revoked_by_user_id
        FROM doctor_note_releases
        WHERE note_id = ?
    """, (
        note_id,
    )).fetchone()


def audit_sharing_action(
    conn,
    user,
    event_type,
    *,
    patient_id,
    note_id=None,
    appointment_id=None,
):
    """
    Write an audit event using the caller's connection.

    Stores metadata only, not clinical-note contents.

    The caller must commit the transaction.
    """

    return record_clinical_audit(
        conn,
        actor_user_id=user["user_id"],
        actor_role=user["role"],
        event_type=event_type,
        patient_id=patient_id,
        note_id=note_id,
        appointment_id=appointment_id,
        outcome="success",
    )


# ============================================================
# DOCTOR: CHECK PATIENT ACCESS STATUS
# ============================================================

@router.get("/doctor/{note_id}")
def doctor_note_release_status(
    note_id: str,
    user: dict = Depends(require_doctor_documents),
):
    with closing(get_db()) as conn:
        note = load_note(conn, note_id, user)
        require_author(note, user)

        release = fetch_release(conn, note_id)

    return {
        "note_id": note_id,
        "note_status": note["status"],
        "released": bool(
            release and release["revoked_at"] is None
        ),
        "released_at": (
            release["released_at"] if release else None
        ),
        "revoked_at": (
            release["revoked_at"] if release else None
        ),
    }


# ============================================================
# DOCTOR: RELEASE SIGNED NOTE TO PATIENT
# ============================================================

@router.post("/doctor/{note_id}/release")
def release_note_to_patient(
    note_id: str,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        note = load_note(conn, note_id, user)
        require_author(note, user)

        if note["status"] != "signed":
            raise HTTPException(
                status_code=409,
                detail="Only signed notes can be released",
            )

        existing = fetch_release(conn, note_id)

        if (
            existing is not None
            and existing["revoked_at"] is None
        ):
            raise HTTPException(
                status_code=409,
                detail="Note is already released",
            )

        timestamp = now_utc()

        conn.execute("""
            INSERT INTO doctor_note_releases (
                note_id,
                released_by_user_id,
                released_at,
                revoked_at,
                revoked_by_user_id
            )
            VALUES (?, ?, ?, NULL, NULL)
            ON CONFLICT(note_id)
            DO UPDATE SET
                released_by_user_id =
                    excluded.released_by_user_id,
                released_at =
                    excluded.released_at,
                revoked_at = NULL,
                revoked_by_user_id = NULL
        """, (
            note_id,
            user["user_id"],
            timestamp,
        ))

        # Existing release history.
        write_release_event(
            conn,
            note_id,
            user["user_id"],
            "released",
        )

        # NEW: centralized clinical audit.
        audit_sharing_action(
            conn,
            user,
            "note_released",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        # Commit release and audit together.
        conn.commit()

    return {
        "note_id": note_id,
        "released": True,
        "released_at": timestamp,
    }


# ============================================================
# DOCTOR: REVOKE PATIENT ACCESS
# ============================================================

@router.post("/doctor/{note_id}/revoke")
def revoke_note_release(
    note_id: str,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        note = load_note(conn, note_id, user)
        require_author(note, user)

        existing = fetch_release(conn, note_id)

        if (
            existing is None
            or existing["revoked_at"] is not None
        ):
            raise HTTPException(
                status_code=409,
                detail="Note is not currently released",
            )

        timestamp = now_utc()

        conn.execute("""
            UPDATE doctor_note_releases
            SET revoked_at = ?,
                revoked_by_user_id = ?
            WHERE note_id = ?
              AND revoked_at IS NULL
        """, (
            timestamp,
            user["user_id"],
            note_id,
        ))

        # Existing release history.
        write_release_event(
            conn,
            note_id,
            user["user_id"],
            "revoked",
        )

        # NEW: centralized clinical audit.
        audit_sharing_action(
            conn,
            user,
            "note_revoked",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return {
        "note_id": note_id,
        "released": False,
        "revoked_at": timestamp,
    }


# ============================================================
# PATIENT: LIST RELEASED CLINICAL NOTES
# ============================================================

@router.get("/my-notes")
def patient_released_notes(
    user: dict = Depends(require_patient_session),
):
    patient_id = user["patient_id"]

    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                n.note_id,
                n.appointment_id,
                n.created_at,
                n.signed_at,
                d.full_name AS doctor_name,
                r.released_at

            FROM doctor_clinical_notes n

            JOIN doctor_note_releases r
              ON r.note_id = n.note_id

            JOIN doctors d
              ON d.doctor_id = n.doctor_id

            WHERE n.patient_id = ?
              AND n.status = 'signed'
              AND r.revoked_at IS NULL

            ORDER BY datetime(r.released_at) DESC
        """, (
            patient_id,
        )).fetchall()

        # NEW: record successful patient list access.
        # A list event may occur even if there are no notes.
        audit_sharing_action(
            conn,
            user,
            "patient_notes_listed",
            patient_id=patient_id,
        )

        conn.commit()

    return {
        "notes": [dict(row) for row in rows],
        "total": len(rows),
    }


# ============================================================
# PATIENT: VIEW RELEASED CLINICAL NOTE
# ============================================================

@router.get("/my-notes/{note_id}")
def patient_released_note_detail(
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
                n.created_at,
                n.signed_at,
                d.full_name AS doctor_name,
                r.released_at

            FROM doctor_clinical_notes n

            JOIN doctor_note_releases r
              ON r.note_id = n.note_id

            JOIN doctors d
              ON d.doctor_id = n.doctor_id

            WHERE n.note_id = ?
              AND n.patient_id = ?
              AND n.status = 'signed'
              AND r.revoked_at IS NULL
        """, (
            note_id,
            user["patient_id"],
        )).fetchone()

        if note is None:
            raise HTTPException(
                status_code=404,
                detail="Released note not found",
            )

        addenda = conn.execute("""
            SELECT
                content,
                created_at
            FROM doctor_note_addenda
            WHERE note_id = ?
            ORDER BY created_at, addendum_id
        """, (
            note_id,
        )).fetchall()

        # NEW: record patient access only after
        # confirming the note belongs to the patient
        # and is signed and actively released.
        audit_sharing_action(
            conn,
            user,
            "patient_note_viewed",
            patient_id=user["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return {
        **dict(note),
        "addenda": [
            dict(addendum)
            for addendum in addenda
        ],
    }
