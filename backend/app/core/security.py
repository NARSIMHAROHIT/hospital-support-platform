
import hashlib
from contextlib import closing
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.database import get_db


def get_current_user(token: str | None):
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with closing(get_db()) as conn:
        user = conn.execute("""
            SELECT
                u.user_id,
                u.patient_id,
                u.doctor_id,
                u.email,
                u.role,
                s.expires_at
            FROM sessions s
            JOIN users u
              ON s.user_id = u.user_id
            WHERE s.token_hash = ?
              AND u.is_active = 1
        """, (token_hash,)).fetchone()

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid session",
            )

        user = dict(user)

        expires_at = datetime.fromisoformat(
            user["expires_at"].replace("Z", "+00:00")
        )

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=401,
                detail="Session expired",
            )

        if user["role"] == "doctor":
            if not user["doctor_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="Doctor account is not linked",
                )

            doctor = conn.execute("""
                SELECT doctor_id
                FROM doctors
                WHERE doctor_id = ?
                  AND is_active = 1
            """, (user["doctor_id"],)).fetchone()

            if doctor is None:
                raise HTTPException(
                    status_code=403,
                    detail="Doctor account is inactive",
                )

    return user
