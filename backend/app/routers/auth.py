import hashlib
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import (
    VerifyMismatchError, VerificationError
)
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.database import get_db
from app.core.security import get_current_user

router = APIRouter()
password_hasher = PasswordHasher()
SESSION_COOKIE = "hospital_session"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

@router.post("/auth/login")
def login(credentials: LoginRequest, response: Response):
    with closing(get_db()) as conn:
        user = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ? AND is_active = 1
        """, (str(credentials.email),)).fetchone()

        # Same response for incorrect email or password
        if user is None:
            raise HTTPException(401, "Invalid credentials")

        try:
            password_hasher.verify(
                user["password_hash"],
                credentials.password
            )
        except (VerifyMismatchError, VerificationError):
            raise HTTPException(401, "Invalid credentials")

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()

        conn.execute("""
            INSERT INTO sessions
            (session_id, user_id, token_hash, expires_at)
            VALUES (?, ?, ?, ?)
        """, (
            str(uuid4()),
            user["user_id"],
            token_hash,
            expires_at
        ))
        conn.commit()

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=False,  # Local HTTP demo only
        samesite="lax",
        max_age=3600,
        path="/"
    )

    return {
        "message": "Login successful",
        "role": user["role"]
    }

@router.get("/auth/me")
def my_profile(
    hospital_session: str | None = Cookie(default=None)
):
    user = get_current_user(hospital_session)

    return {
        "user_id": user["user_id"],
        "patient_id": user["patient_id"],
        "email": user["email"],
        "role": user["role"]
    }

@router.post("/auth/logout")
def logout(
    response: Response,
    hospital_session: str | None = Cookie(default=None)
):
    if hospital_session:
        token_hash = hashlib.sha256(
            hospital_session.encode("utf-8")
        ).hexdigest()

        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,)
            )
            conn.commit()

    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        samesite="lax"
    )

    return {"message": "Logged out successfully"}
