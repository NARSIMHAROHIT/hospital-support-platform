
import json
import sqlite3

from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.core.care_access import authorize_record_action
from app.core.clinical_audit import record_clinical_audit
from app.routers.appointments import check_request_origin
from app.routers.doctor_documents import require_doctor_documents


router = APIRouter(
    prefix="/doctor/clinical-notes",
    tags=["Doctor Clinical Notes"],
)


# ============================================================
# REQUEST MODELS
# ============================================================

class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1)
    appointment_id: str = Field(min_length=1)
    observations: str = Field(min_length=1, max_length=5000)
    assessment: str = Field(default="", max_length=5000)
    treatment_plan: str = Field(default="", max_length=5000)


class NoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: str | None = Field(
        default=None,
        min_length=1,
        max_length=5000,
    )

    assessment: str | None = Field(
        default=None,
        max_length=5000,
    )

    treatment_plan: str | None = Field(
        default=None,
        max_length=5000,
    )


class AddendumCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        min_length=1,
        max_length=5000,
    )


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def note_snapshot(note):
    return {
        "note_id": note["note_id"],
        "patient_id": note["patient_id"],
        "appointment_id": note["appointment_id"],
        "author_user_id": note["author_user_id"],
        "observations": note["observations"],
        "assessment": note["assessment"],
        "treatment_plan": note["treatment_plan"],
        "status": note["status"],
        "updated_at": note["updated_at"],
        "signed_at": note["signed_at"],
    }


def record_event(
    conn,
    note,
    user_id,
    event_type,
    extra=None,
):
    """
    Preserve the existing note-version event history.
    """

    snapshot = note_snapshot(note)

    if extra:
        snapshot.update(extra)

    conn.execute("""
        INSERT INTO doctor_note_events (
            event_id,
            note_id,
            actor_user_id,
            event_type,
            snapshot_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(uuid4()),
        note["note_id"],
        user_id,
        event_type,
        json.dumps(snapshot),
        now_utc(),
    ))


def audit_doctor_action(
    conn,
    user,
    event_type,
    *,
    patient_id,
    note_id=None,
    appointment_id=None,
):
    """
    Record an audit event without medical-note contents.

    This uses the same SQLite transaction as the
    surrounding clinical operation.

    The caller must commit.
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


def load_note(conn, note_id, user):
    note = conn.execute("""
        SELECT *
        FROM doctor_clinical_notes
        WHERE note_id = ?
    """, (note_id,)).fetchone()

    if note is None:
        raise HTTPException(
            status_code=404,
            detail="Clinical note not found",
        )

    authorize_record_action(
        conn,
        user,
        note["patient_id"],
        "records:read",
    )

    # Other authorized doctors may view signed notes.
    # Unsigned drafts remain private to the author.
    if (
        note["status"] == "draft"
        and note["author_user_id"] != user["user_id"]
    ):
        raise HTTPException(
            status_code=404,
            detail="Clinical note not found",
        )

    return note


def require_author(note, user):
    if note["author_user_id"] != user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the authoring doctor may edit this note",
        )


# ============================================================
# CREATE CLINICAL NOTE
# ============================================================

@router.post("", status_code=201)
def create_clinical_note(
    payload: NoteCreate,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    note_id = str(uuid4())
    timestamp = now_utc()

    if not payload.observations.strip():
        raise HTTPException(
            status_code=422,
            detail="Observations are required",
        )

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        authorize_record_action(
            conn,
            user,
            payload.patient_id,
            "notes:create",
        )

        appointment = conn.execute("""
            SELECT
                appointment_id,
                status
            FROM appointments
            WHERE appointment_id = ?
              AND patient_id = ?
              AND doctor_id = ?
        """, (
            payload.appointment_id,
            payload.patient_id,
            user["doctor_id"],
        )).fetchone()

        if appointment is None:
            raise HTTPException(
                status_code=404,
                detail="Appointment not found",
            )

        if appointment["status"] not in ("booked", "completed"):
            raise HTTPException(
                status_code=409,
                detail="Cannot document a cancelled appointment",
            )

        try:
            conn.execute("""
                INSERT INTO doctor_clinical_notes (
                    note_id,
                    patient_id,
                    doctor_id,
                    appointment_id,
                    author_user_id,
                    observations,
                    assessment,
                    treatment_plan,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    'draft', ?, ?
                )
            """, (
                note_id,
                payload.patient_id,
                user["doctor_id"],
                payload.appointment_id,
                user["user_id"],
                payload.observations.strip(),
                payload.assessment.strip(),
                payload.treatment_plan.strip(),
                timestamp,
                timestamp,
            ))

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="A note already exists for this appointment",
            )

        note = conn.execute("""
            SELECT *
            FROM doctor_clinical_notes
            WHERE note_id = ?
        """, (note_id,)).fetchone()

        record_event(
            conn,
            note,
            user["user_id"],
            "created",
        )

        # NEW: clinical audit event.
        audit_doctor_action(
            conn,
            user,
            "note_created",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return dict(note)


# ============================================================
# LIST PATIENT CLINICAL NOTES
# ============================================================

@router.get("/patient/{patient_id}")
def list_patient_clinical_notes(
    patient_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_doctor_documents),
):
    with closing(get_db()) as conn:
        authorize_record_action(
            conn,
            user,
            patient_id,
            "records:read",
        )

        rows = conn.execute("""
            SELECT
                n.*,
                a.status AS appointment_status,
                s.starts_at AS appointment_starts_at,
                s.ends_at AS appointment_ends_at,
                d.full_name AS doctor_name

            FROM doctor_clinical_notes n

            LEFT JOIN appointments a
              ON a.appointment_id = n.appointment_id

            LEFT JOIN doctor_slots s
              ON s.slot_id = a.slot_id

            LEFT JOIN doctors d
              ON d.doctor_id = n.doctor_id

            WHERE n.patient_id = ?
              AND (
                  n.status = 'signed'
                  OR n.author_user_id = ?
              )

            ORDER BY
                n.created_at DESC,
                n.note_id DESC

            LIMIT ? OFFSET ?
        """, (
            patient_id,
            user["user_id"],
            limit,
            offset,
        )).fetchall()

        # NEW: log successful list access.
        audit_doctor_action(
            conn,
            user,
            "doctor_notes_listed",
            patient_id=patient_id,
        )

        conn.commit()

    return {
        "patient_id": patient_id,
        "notes": [
            {
                **dict(row),
                "is_author": (
                    row["author_user_id"] == user["user_id"]
                ),
            }
            for row in rows
        ],
    }


# ============================================================
# GET CLINICAL NOTE DETAILS
# ============================================================

@router.get("/{note_id}")
def get_clinical_note(
    note_id: str,
    user: dict = Depends(require_doctor_documents),
):
    with closing(get_db()) as conn:
        note = load_note(conn, note_id, user)

        appointment = conn.execute("""
            SELECT
                a.status AS appointment_status,
                s.starts_at AS appointment_starts_at,
                s.ends_at AS appointment_ends_at,
                d.full_name AS doctor_name

            FROM doctor_clinical_notes n

            LEFT JOIN appointments a
              ON a.appointment_id = n.appointment_id

            LEFT JOIN doctor_slots s
              ON s.slot_id = a.slot_id

            LEFT JOIN doctors d
              ON d.doctor_id = n.doctor_id

            WHERE n.note_id = ?
        """, (note_id,)).fetchone()

        addenda = conn.execute("""
            SELECT
                addendum_id,
                author_user_id,
                content,
                created_at
            FROM doctor_note_addenda
            WHERE note_id = ?
            ORDER BY created_at, addendum_id
        """, (note_id,)).fetchall()

        # NEW: log successful note viewing.
        audit_doctor_action(
            conn,
            user,
            "doctor_note_viewed",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return {
        **dict(note),
        **(dict(appointment) if appointment else {}),
        "addenda": [dict(row) for row in addenda],
    }


# ============================================================
# EDIT EXISTING DRAFT
# ============================================================

@router.patch("/{note_id}")
def edit_clinical_note(
    note_id: str,
    payload: NoteUpdate,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    changes = payload.model_dump(exclude_unset=True)

    if not changes or any(
        value is None for value in changes.values()
    ):
        raise HTTPException(
            status_code=422,
            detail="Provide at least one valid field",
        )

    if (
        "observations" in changes
        and not changes["observations"].strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="Observations cannot be empty",
        )

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        note = load_note(conn, note_id, user)
        require_author(note, user)

        if note["status"] != "draft":
            raise HTTPException(
                status_code=409,
                detail="Signed notes cannot be edited",
            )

        updated_values = {
            "observations": changes.get(
                "observations",
                note["observations"],
            ),
            "assessment": changes.get(
                "assessment",
                note["assessment"],
            ),
            "treatment_plan": changes.get(
                "treatment_plan",
                note["treatment_plan"],
            ),
        }

        updated_values = {
            key: value.strip()
            for key, value in updated_values.items()
        }

        conn.execute("""
            UPDATE doctor_clinical_notes
            SET observations = ?,
                assessment = ?,
                treatment_plan = ?,
                updated_at = ?
            WHERE note_id = ?
              AND author_user_id = ?
              AND status = 'draft'
        """, (
            updated_values["observations"],
            updated_values["assessment"],
            updated_values["treatment_plan"],
            now_utc(),
            note_id,
            user["user_id"],
        ))

        updated = conn.execute("""
            SELECT *
            FROM doctor_clinical_notes
            WHERE note_id = ?
        """, (note_id,)).fetchone()

        record_event(
            conn,
            updated,
            user["user_id"],
            "edited",
        )

        # NEW: audit manual saves and autosaves.
        audit_doctor_action(
            conn,
            user,
            "note_edited",
            patient_id=updated["patient_id"],
            note_id=updated["note_id"],
            appointment_id=updated["appointment_id"],
        )

        conn.commit()

    return dict(updated)


# ============================================================
# SIGN CLINICAL NOTE
# ============================================================

@router.post("/{note_id}/sign")
def sign_clinical_note(
    note_id: str,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        note = load_note(conn, note_id, user)
        require_author(note, user)

        if note["status"] != "draft":
            raise HTTPException(
                status_code=409,
                detail="Note has already been signed",
            )

        timestamp = now_utc()

        conn.execute("""
            UPDATE doctor_clinical_notes
            SET status = 'signed',
                signed_at = ?,
                updated_at = ?
            WHERE note_id = ?
              AND author_user_id = ?
              AND status = 'draft'
        """, (
            timestamp,
            timestamp,
            note_id,
            user["user_id"],
        ))

        signed = conn.execute("""
            SELECT *
            FROM doctor_clinical_notes
            WHERE note_id = ?
        """, (note_id,)).fetchone()

        record_event(
            conn,
            signed,
            user["user_id"],
            "signed",
        )

        # NEW: note signing audit.
        audit_doctor_action(
            conn,
            user,
            "note_signed",
            patient_id=signed["patient_id"],
            note_id=signed["note_id"],
            appointment_id=signed["appointment_id"],
        )

        conn.commit()

    return dict(signed)


# ============================================================
# ADD CORRECTION TO SIGNED NOTE
# ============================================================

@router.post("/{note_id}/addenda", status_code=201)
def add_clinical_note_addendum(
    note_id: str,
    payload: AddendumCreate,
    user: dict = Depends(require_doctor_documents),
    _origin=Depends(check_request_origin),
):
    content = payload.content.strip()

    if not content:
        raise HTTPException(
            status_code=422,
            detail="Addendum cannot be empty",
        )

    addendum_id = str(uuid4())
    timestamp = now_utc()

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        note = load_note(conn, note_id, user)
        require_author(note, user)

        if note["status"] != "signed":
            raise HTTPException(
                status_code=409,
                detail="Addenda require a signed note",
            )

        conn.execute("""
            INSERT INTO doctor_note_addenda (
                addendum_id,
                note_id,
                author_user_id,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            addendum_id,
            note_id,
            user["user_id"],
            content,
            timestamp,
        ))

        record_event(
            conn,
            note,
            user["user_id"],
            "addendum_added",
            {
                "addendum_id": addendum_id,
                "addendum_content": content,
            },
        )

        # NEW: addendum audit.
        audit_doctor_action(
            conn,
            user,
            "note_addendum_added",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return {
        "addendum_id": addendum_id,
        "note_id": note_id,
        "content": content,
        "created_at": timestamp,
    }


# ============================================================
# LIST APPOINTMENTS AVAILABLE FOR NOTES
# ============================================================

@router.get("/patient/{patient_id}/appointments")
def list_patient_note_appointments(
    patient_id: str,
    user: dict = Depends(require_doctor_documents),
):
    with closing(get_db()) as conn:
        authorize_record_action(
            conn,
            user,
            patient_id,
            "records:read",
        )

        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.patient_id,
                a.status,
                s.starts_at,
                s.ends_at
            FROM appointments a

            JOIN doctor_slots s
              ON s.slot_id = a.slot_id
             AND s.doctor_id = a.doctor_id

            WHERE a.patient_id = ?
              AND a.doctor_id = ?
              AND a.status IN ('booked', 'completed')

            ORDER BY datetime(s.starts_at) DESC
        """, (
            patient_id,
            user["doctor_id"],
        )).fetchall()

    return {
        "patient_id": patient_id,
        "appointments": [dict(row) for row in rows],
    }


# ============================================================
# LEGACY NOTE RELEASE ENDPOINT
#
# Preserved for compatibility.
# The current Patient Portal uses:
# /clinical/note-sharing/...
# ============================================================

@router.post("/{note_id}/release", status_code=201)
def release_clinical_note_to_patient(
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

        existing = conn.execute("""
            SELECT note_id
            FROM patient_note_releases
            WHERE note_id = ?
        """, (note_id,)).fetchone()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Note has already been released",
            )

        timestamp = now_utc()

        conn.execute("""
            INSERT INTO patient_note_releases (
                note_id,
                released_by_user_id,
                released_at
            )
            VALUES (?, ?, ?)
        """, (
            note_id,
            user["user_id"],
            timestamp,
        ))

        # Log successful use of the legacy release route.
        audit_doctor_action(
            conn,
            user,
            "note_released",
            patient_id=note["patient_id"],
            note_id=note["note_id"],
            appointment_id=note["appointment_id"],
        )

        conn.commit()

    return {
        "note_id": note_id,
        "released_to_patient": True,
        "released_at": timestamp,
    }
