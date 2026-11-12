"""
Read-only appointment tools for the Patient AI Assistant.

Features:
- Retrieve only the authenticated patient's appointments
- Show doctor name, specialty, department, date and status
- Display appointment times in a configured timezone
- Never modify bookings
- Never send appointment details to an external LLM

Prototype only: use fictional patient data.
"""

import os
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.database import get_db
from app.routers.appointments import parse_utc


MAX_APPOINTMENTS = 20


# ============================================================
# TIMEZONE
# ============================================================

def get_display_timezone():
    """
    Configurable timezone for appointment display.

    Defaults to UTC until the portal supports
    a verified patient-specific timezone.
    """

    name = os.getenv(
        "HOSPITAL_AI_DISPLAY_TZ",
        "UTC",
    )

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def format_appointment_time(value):
    """
    Format a stored UTC appointment time into
    the configured display timezone.
    """

    utc_time = parse_utc(value)

    local_time = utc_time.astimezone(
        get_display_timezone()
    )

    return local_time.strftime(
        "%A, %B %d, %Y at %I:%M %p %Z"
    )


# ============================================================
# PATIENT APPOINTMENT LOOKUP
# ============================================================

def get_upcoming_appointments(
    patient_id: str,
    limit: int = 10,
):
    """
    Retrieve upcoming booked appointments.

    SECURITY:
    patient_id must come from the authenticated
    patient session, never from a chat message.
    """

    if (
        not isinstance(patient_id, str)
        or not patient_id.strip()
    ):
        raise ValueError(
            "Authenticated patient ID is required"
        )

    limit = max(
        1,
        min(int(limit), MAX_APPOINTMENTS),
    )

    now = datetime.now(timezone.utc)

    with closing(get_db()) as conn:
        rows = conn.execute(
            """
            SELECT
                a.appointment_id,
                a.doctor_id,
                a.slot_id,
                a.status,

                d.full_name AS doctor_name,
                d.specialization,
                d.department,

                s.starts_at,
                s.ends_at

            FROM appointments a

            JOIN doctors d
              ON a.doctor_id = d.doctor_id

            JOIN doctor_slots s
              ON a.slot_id = s.slot_id

            WHERE a.patient_id = ?
              AND a.status = 'booked'

            ORDER BY s.starts_at ASC
            """,
            (patient_id,),
        ).fetchall()

    upcoming = []

    for row in rows:
        start_time = parse_utc(
            row["starts_at"]
        )

        if start_time < now:
            continue

        upcoming.append({
            "appointment_id": row["appointment_id"],
            "doctor_id": row["doctor_id"],
            "slot_id": row["slot_id"],

            "doctor_name": row["doctor_name"],
            "specialization": row["specialization"],
            "department": row["department"],

            "status": row["status"],
            "starts_at": start_time.isoformat(),

            "ends_at": parse_utc(
                row["ends_at"]
            ).isoformat(),
        })

        if len(upcoming) >= limit:
            break

    return upcoming


# ============================================================
# FORMAT THE RESPONSE
# ============================================================

def format_appointments_for_patient(
    appointments,
):
    """
    Generate a deterministic appointment response.

    No LLM call is needed.
    """

    if not appointments:
        return (
            "You have no upcoming booked appointments.\n\n"
            "To schedule a new appointment, select "
            "Find Doctors in your Patient Portal."
        )

    count = len(appointments)

    heading = (
        f"You have {count} upcoming booked "
        f"appointment{'s' if count != 1 else ''} "
        "listed below:"
    )

    lines = [heading]

    for index, appointment in enumerate(
        appointments,
        start=1,
    ):
        doctor = (
            appointment.get("doctor_name")
            or "Doctor name unavailable"
        )

        specialization = (
            appointment.get("specialization")
            or "Not specified"
        )

        department = (
            appointment.get("department")
            or "Not specified"
        )

        appointment_time = (
            format_appointment_time(
                appointment["starts_at"]
            )
        )

        status = str(
            appointment.get("status", "booked")
        ).capitalize()

        lines.extend([
            "",
            f"{index}. {appointment_time}",
            f"   Doctor: {doctor}",
            f"   Specialty: {specialization}",
            f"   Department: {department}",
            f"   Status: {status}",
        ])

    lines.extend([
        "",
        "Open My Appointments in your Patient Portal "
        "to review booking details and available actions.",
        "",
        "To schedule a new appointment, "
        "select Find Doctors.",
    ])

    return "\n".join(lines)
