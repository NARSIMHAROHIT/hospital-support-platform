import hashlib
from contextlib import closing
from datetime import datetime, timezone

from fastapi import HTTPException
from app.core.database import get_db

def get_current_user(token: str | None):
    if not token:
        raise HTTPException(401, "Authentication required")

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with closing(get_db()) as conn:
        user = conn.execute("""
            SELECT u.user_id, u.patient_id,
                   u.email, u.role, s.expires_at
            FROM sessions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.token_hash = ?
              AND u.is_active = 1
        """, (token_hash,)).fetchone()

    if user is None:
        raise HTTPException(401, "Invalid session")

    if datetime.fromisoformat(
        user["expires_at"]
    ) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")

    return dict(user)
