
from contextlib import closing
from datetime import datetime, timezone
from app.core.database import get_db


def parse_time(value):
    value = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


with closing(get_db()) as conn:
    appointments = conn.execute("""
        SELECT
            a.appointment_id,
            a.patient_id,
            a.doctor_id,
            s.starts_at,
            s.ends_at
        FROM appointments a
        JOIN doctor_slots s ON a.slot_id = s.slot_id
        WHERE a.status = 'booked'
    """).fetchall()

    conflicts = []

    for i, first in enumerate(appointments):
        for second in appointments[i + 1:]:
            same_patient = (
                first["patient_id"] == second["patient_id"]
            )

            same_doctor = (
                first["doctor_id"] == second["doctor_id"]
            )

            if not (same_patient or same_doctor):
                continue

            overlaps = (
                parse_time(first["starts_at"]) <
                parse_time(second["ends_at"])
                and
                parse_time(first["ends_at"]) >
                parse_time(second["starts_at"])
            )

            if overlaps:
                conflicts.append((
                    "PATIENT" if same_patient else "DOCTOR",
                    first["appointment_id"],
                    second["appointment_id"],
                ))

    print("Overlapping appointment pairs:", len(conflicts))

    for conflict in conflicts:
        print(conflict)
