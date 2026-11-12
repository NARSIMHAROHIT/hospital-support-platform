
from contextlib import closing
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
import sys

# Allow imports from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import get_db


HOSPITAL_TIMEZONE = ZoneInfo("America/Chicago")

# Fictional doctor records for local development.
DEMO_DOCTORS = [
    {
        "full_name": "Dr. Maya Patel",
        "specialization": "Cardiology",
        "department": "Cardiology",
    },
    {
        "full_name": "Dr. James Wilson",
        "specialization": "Neurology",
        "department": "Neurology",
    },
    {
        "full_name": "Dr. Sarah Lee",
        "specialization": "Orthopedics",
        "department": "Orthopedics",
    },
]

# Appointment starting hours in hospital-local time.
SLOT_HOURS = [9, 10, 11, 14, 15]
SLOT_DURATION_MINUTES = 30
WEEKDAYS_TO_GENERATE = 10


def parse_datetime(value):
    """Parse existing SQLite timestamps for comparisons."""
    if not value:
        raise ValueError("Missing appointment timestamp")

    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        # Existing project timestamps are treated as UTC.
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def overlaps(start, end, existing_slots):
    """Reject any overlapping doctor schedule entry."""
    for existing in existing_slots:
        existing_start = parse_datetime(existing["starts_at"])
        existing_end = parse_datetime(existing["ends_at"])

        if start < existing_end and end > existing_start:
            return True

    return False


def upcoming_weekdays(count):
    """Get upcoming weekdays, starting tomorrow."""
    today = datetime.now(HOSPITAL_TIMEZONE).date()
    current = today + timedelta(days=1)
    result = []

    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)

        current += timedelta(days=1)

    return result


def seed():
    created_doctors = 0
    created_slots = 0

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        try:
            dates = upcoming_weekdays(
                WEEKDAYS_TO_GENERATE
            )

            for doctor in DEMO_DOCTORS:
                # Reuse existing fictional doctor records.
                existing = conn.execute("""
                    SELECT doctor_id, is_active
                    FROM doctors
                    WHERE full_name = ?
                      AND department = ?
                    LIMIT 1
                """, (
                    doctor["full_name"],
                    doctor["department"],
                )).fetchone()

                if existing:
                    doctor_id = existing["doctor_id"]

                    if not existing["is_active"]:
                        print(
                            "Skipped inactive doctor:",
                            doctor["full_name"]
                        )
                        continue
                else:
                    doctor_id = str(uuid4())

                    conn.execute("""
                        INSERT INTO doctors (
                            doctor_id,
                            full_name,
                            specialization,
                            department,
                            is_active
                        )
                        VALUES (?, ?, ?, ?, 1)
                    """, (
                        doctor_id,
                        doctor["full_name"],
                        doctor["specialization"],
                        doctor["department"],
                    ))

                    created_doctors += 1

                existing_slots = [
                    dict(row)
                    for row in conn.execute("""
                        SELECT starts_at, ends_at
                        FROM doctor_slots
                        WHERE doctor_id = ?
                    """, (doctor_id,)).fetchall()
                ]

                doctor_slot_count = 0

                for day in dates:
                    for hour in SLOT_HOURS:
                        local_start = datetime.combine(
                            day,
                            time(hour, 0),
                            tzinfo=HOSPITAL_TIMEZONE,
                        )

                        local_end = local_start + timedelta(
                            minutes=SLOT_DURATION_MINUTES
                        )

                        start = local_start.astimezone(
                            timezone.utc
                        )

                        end = local_end.astimezone(
                            timezone.utc
                        )

                        if overlaps(
                            start,
                            end,
                            existing_slots,
                        ):
                            continue

                        conn.execute("""
                            INSERT INTO doctor_slots (
                                slot_id,
                                doctor_id,
                                starts_at,
                                ends_at
                            )
                            VALUES (?, ?, ?, ?)
                        """, (
                            str(uuid4()),
                            doctor_id,
                            start.isoformat(),
                            end.isoformat(),
                        ))

                        existing_slots.append({
                            "starts_at": start.isoformat(),
                            "ends_at": end.isoformat(),
                        })

                        created_slots += 1
                        doctor_slot_count += 1

                print(
                    f"{doctor['full_name']}: "
                    f"{doctor_slot_count} new slots"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    print()
    print("Doctors created:", created_doctors)
    print("Appointment slots created:", created_slots)
    print("Development schedule setup complete.")


if __name__ == "__main__":
    if "--seed-demo" not in sys.argv:
        raise SystemExit(
            "Development data only. "
            "Run with --seed-demo to confirm."
        )

    seed()
