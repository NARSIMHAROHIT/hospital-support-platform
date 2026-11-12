"""
Natural-language appointment intent classification.

This module:
- Identifies appointment questions
- Extracts basic filters
- Does not access patient data
- Does not call an LLM
- Does not perform booking actions
"""

import re


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

SPECIALTIES = (
    "cardiology",
    "neurology",
    "dermatology",
    "orthopedics",
    "pediatrics",
    "radiology",
)

MEDICAL_SAFETY_TERMS = (
    "emergency",
    "chest pain",
    "trouble breathing",
    "bleeding",
    "symptom",
    "medication",
    "dosage",
    "diagnosis",
    "treatment",
    "suicide",
)


def normalize(text):
    return " ".join(
        re.findall(r"[a-z0-9]+", text.casefold())
    )


def contains_term(text, term):
    pattern = (
        r"(?<!\w)"
        + re.escape(normalize(term))
        + r"s?(?!\w)"
    )
    return re.search(pattern, text) is not None


def classify_appointment_question(message):
    """
    Return a structured intent dictionary or None.

    No patient information is accepted or retrieved.
    """

    if not isinstance(message, str):
        return None

    text = normalize(message)

    if not text:
        return None

    # Medical questions must use the existing
    # medical safety routing.
    if any(
        contains_term(text, term)
        for term in MEDICAL_SAFETY_TERMS
    ):
        return None

    appointment_context = any(
        contains_term(text, term)
        for term in (
            "appointment",
            "booking",
            "scheduled",
            "schedule",
            "doctor",
        )
    )

    if not appointment_context:
        return None

    # Booking instructions
    if (
        any(
            contains_term(text, term)
            for term in ("book", "schedule", "make")
        )
        and any(
            contains_term(text, term)
            for term in ("how", "where", "new", "can")
        )
        and contains_term(text, "appointment")
    ):
        return {
            "action": "booking_help",
            "weekday": None,
            "specialty": None,
            "next_only": False,
        }

    # Recognize day constraints, without resolving
    # calendar dates in this classifier.
    weekday = None

    for day in WEEKDAYS:
        if (
            f"this {day}" in text
            or f"next {day}" in text
        ):
            weekday = day
            break

    # Recognize available specialty keywords.
    specialty = None

    for name in SPECIALTIES:
        if contains_term(text, name):
            specialty = name
            break

    next_only = contains_term(text, "next")

    # "Next Friday" is a date constraint,
    # not necessarily a next-appointment request.
    if weekday and (
        f"next {weekday}" in text
    ):
        next_only = False

    if weekday:
        action = "by_weekday"
    elif specialty and not next_only:
        action = "by_specialty"
    elif next_only:
        action = "next"
    elif any(
        contains_term(text, term)
        for term in (
            "appointment",
            "scheduled",
            "booking",
        )
    ):
        action = "upcoming"
    else:
        return None

    return {
        "action": action,
        "weekday": weekday,
        "specialty": specialty,
        "next_only": next_only,
    }
