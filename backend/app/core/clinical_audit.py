
from datetime import datetime, timezone
from uuid import uuid4


ALLOWED_EVENT_TYPES = {
    "note_created",
    "note_edited",
    "note_signed",
    "note_addendum_added",
    "note_released",
    "note_revoked",
    "doctor_note_viewed",
    "patient_note_viewed",
    "doctor_notes_listed",
    "patient_notes_listed",
    "medical_document_downloaded",
}

ALLOWED_ROLES = {
    "doctor",
    "patient",
    "nurse",
    "admin",
    "system",
}

ALLOWED_OUTCOMES = {
    "success",
    "denied",
}


def record_clinical_audit(
    conn,
    *,
    actor_user_id: str,
    actor_role: str,
    event_type: str,
    patient_id: str | None = None,
    note_id: str | None = None,
    appointment_id: str | None = None,
    outcome: str = "success",
):
    """
    Record a clinical audit event.

    Uses the caller's existing SQLite connection.

    IMPORTANT:
    - Does not open a new database connection.
    - Does not commit the transaction.
    - Does not store medical note contents.
    - Does not store passwords or session cookies.
    - Raises errors instead of silently dropping events.

    The calling endpoint is responsible for committing.

    Example:
        record_clinical_audit(
            conn,
            actor_user_id=user["user_id"],
            actor_role=user["role"],
            event_type="note_signed",
            patient_id=patient_id,
            note_id=note_id,
            appointment_id=appointment_id,
        )

        conn.commit()
    """

    if not isinstance(actor_user_id, str) or not actor_user_id.strip():
        raise ValueError(
            "A valid actor_user_id is required"
        )

    if actor_role not in ALLOWED_ROLES:
        raise ValueError(
            f"Unsupported audit actor role: {actor_role}"
        )

    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"Unsupported clinical audit event: {event_type}"
        )

    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(
            f"Unsupported audit outcome: {outcome}"
        )

    audit_id = str(uuid4())

    occurred_at = datetime.now(
        timezone.utc
    ).isoformat()

    conn.execute("""
        INSERT INTO clinical_audit_events (
            audit_id,
            actor_user_id,
            actor_role,
            patient_id,
            note_id,
            appointment_id,
            event_type,
            outcome,
            occurred_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        audit_id,
        actor_user_id,
        actor_role,
        patient_id,
        note_id,
        appointment_id,
        event_type,
        outcome,
        occurred_at,
    ))

    return audit_id
