
from fastapi import Cookie, HTTPException

from app.core.security import get_current_user


def require_authenticated_user(
    hospital_session: str | None = Cookie(default=None),
):
    return get_current_user(hospital_session)


def require_patient(
    hospital_session: str | None = Cookie(default=None),
):
    user = get_current_user(hospital_session)

    if user["role"] != "patient" or not user["patient_id"]:
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    return user


def require_admin(
    hospital_session: str | None = Cookie(default=None),
):
    user = get_current_user(hospital_session)

    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    return user
