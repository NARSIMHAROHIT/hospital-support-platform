
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


# Temporary local-demo policy.
# A hospital must approve its actual retention/access policy.
FOLLOW_UP_ACCESS_DAYS = 30


ROLE_PERMISSIONS = {
    "patient": {
        "records:read",
        "records:upload",
    },
    "doctor": {
        "records:read",
        "records:upload",
        "notes:create",
        "notes:read_signed",
    },
    "nurse": {
        "records:read",
        "notes:read_signed",
    },
}


def appointment_access_cutoff():
    return (
        datetime.now(timezone.utc)
        - timedelta(days=FOLLOW_UP_ACCESS_DAYS)
    ).isoformat()


def authorize_record_action(
    conn,
    user: dict,
    patient_id: str,
    action: str,
):
    role = user.get("role")

    if action not in ROLE_PERMISSIONS.get(role, set()):
        raise HTTPException(
            status_code=403,
            detail="Action not permitted",
        )

    # Patients can access only their own records.
    if role == "patient":
        if user.get("patient_id") != patient_id:
            raise HTTPException(
                status_code=404,
                detail="Medical records not found",
            )
        return

    staff_user_id = user.get("user_id")

    if not staff_user_id:
        raise HTTPException(
            status_code=403,
            detail="Staff account not identified",
        )

    if role == "doctor" and not user.get("doctor_id"):
        raise HTTPException(
            status_code=403,
            detail="Doctor account is not linked",
        )

    # First check explicit care-team assignments.
    manual_assignment = conn.execute("""
        SELECT 1
        FROM care_team_assignments c
        JOIN users u
          ON u.user_id = c.staff_user_id
        LEFT JOIN doctors d
          ON d.doctor_id = u.doctor_id
        WHERE c.patient_id = ?
          AND c.staff_user_id = ?
          AND c.revoked_at IS NULL
          AND u.is_active = 1
          AND u.role = ?
          AND (
              u.role = 'nurse'
              OR (
                  u.role = 'doctor'
                  AND u.doctor_id IS NOT NULL
                  AND d.is_active = 1
              )
          )
        LIMIT 1
    """, (
        patient_id,
        staff_user_id,
        role,
    )).fetchone()

    if manual_assignment is not None:
        return

    # Doctors can also access patients through a
    # current confirmed appointment relationship.
    # Nurses do not receive this automatic access.
    if role == "doctor":
        appointment = conn.execute("""
            SELECT 1
            FROM appointments a
            JOIN doctor_slots s
              ON s.slot_id = a.slot_id
            JOIN doctors d
              ON d.doctor_id = a.doctor_id
            JOIN users u
              ON u.doctor_id = a.doctor_id
            WHERE a.patient_id = ?
              AND a.doctor_id = ?
              AND u.user_id = ?
              AND u.role = 'doctor'
              AND u.is_active = 1
              AND d.is_active = 1
              AND a.status IN ('booked', 'completed')
              AND datetime(s.ends_at) >= datetime(?)
            LIMIT 1
        """, (
            patient_id,
            user["doctor_id"],
            staff_user_id,
            appointment_access_cutoff(),
        )).fetchone()

        if appointment is not None:
            return

    raise HTTPException(
        status_code=404,
        detail="Medical records not found",
    )
