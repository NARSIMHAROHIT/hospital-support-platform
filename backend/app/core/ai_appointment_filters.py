"""
Appointment filters for the Patient AI Assistant.

- Filters already-authorized appointment records.
- Supports next appointment, weekday and specialty.
- Uses the configured appointment display timezone.
- Does not access the database or call Groq.
- Does not modify appointments.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.ai_appointment_tools import (
    get_display_timezone,
)
from app.routers.appointments import parse_utc
from app.core.ai_appointment_intents import normalize


WEEKDAY_NUMBERS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def resolve_weekday_date(
    weekday,
    message,
    today=None,
):
    """
    Resolve relative weekdays in clinic-local time.

    'this Friday' = Friday of the current calendar week.
    'next Friday' = Friday of the following calendar week.
    'Friday' = nearest Friday, including today.
    """

    if weekday not in WEEKDAY_NUMBERS:
        return None

    if today is None:
        today = datetime.now(
            get_display_timezone()
        ).date()

    weekday_number = WEEKDAY_NUMBERS[weekday]
    normalized = normalize(message)

    week_start = today - timedelta(
        days=today.weekday()
    )

    if f"next {weekday}" in normalized:
        return week_start + timedelta(
            days=7 + weekday_number
        )

    if f"this {weekday}" in normalized:
        return week_start + timedelta(
            days=weekday_number
        )

    days_ahead = (
        weekday_number - today.weekday()
    ) % 7

    return today + timedelta(days=days_ahead)


def filter_appointments_for_intent(
    appointments,
    intent,
    message,
    today=None,
    display_tz=None,
):
    """
    Select matching appointment records.

    appointments:
        Results from get_upcoming_appointments().
        They must already belong to the authenticated
        patient.

    intent:
        Result from classify_appointment_question().

    Returns a list of matching appointments.
    """

    if not isinstance(intent, dict):
        return []

    action = intent.get("action")

    if action not in {
        "next",
        "upcoming",
        "by_weekday",
        "by_specialty",
    }:
        return []

    if display_tz is None:
        display_tz = get_display_timezone()

    if today is None:
        today = datetime.now(display_tz).date()

    result = list(appointments)

    # --------------------------------------------------------
    # FILTER BY SPECIALTY
    # --------------------------------------------------------

    specialty = intent.get("specialty")

    if specialty:
        result = [
            appointment
            for appointment in result
            if specialty.casefold() in (
                appointment.get("specialization") or ""
            ).casefold()
        ]

    # --------------------------------------------------------
    # FILTER BY WEEKDAY / DATE
    # --------------------------------------------------------

    weekday = intent.get("weekday")

    if weekday:
        target_date = resolve_weekday_date(
            weekday=weekday,
            message=message,
            today=today,
        )

        if target_date is None:
            return []

        result = [
            appointment
            for appointment in result
            if parse_utc(
                appointment["starts_at"]
            ).astimezone(
                display_tz
            ).date() == target_date
        ]

    # --------------------------------------------------------
    # RETURN NEXT APPOINTMENT
    # --------------------------------------------------------

    result.sort(
        key=lambda appointment: parse_utc(
            appointment["starts_at"]
        )
    )

    if action == "next":
        return result[:1]

    return result
