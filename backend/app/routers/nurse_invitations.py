
import hashlib
import os
import re
import secrets
import sqlite3

from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.permissions import require_admin
from app.routers.appointments import check_request_origin


router = APIRouter(tags=["Nurse Invitations"])
password_hasher = PasswordHasher()


class NurseInvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)


class NurseInvitationAccept(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=128)


def utc_now():
    return datetime.now(timezone.utc)


def token_digest(token: str):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str):
    email = email.strip().lower()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(
            status_code=422,
            detail="Invalid email address",
        )

    return email


@router.post("/admin/nurse-invitations", status_code=201)
def create_nurse_invitation(
    payload: NurseInvitationCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    # Email invitation delivery is deferred.
    # Secret tokens can be printed ONLY in local development.
    if (
        os.getenv("APP_ENV") != "development"
        or os.getenv("NURSE_INVITE_DELIVERY_MODE") != "console"
    ):
        raise HTTPException(
            status_code=503,
            detail="Nurse invitation delivery is not configured",
        )

    admin_id = admin.get("user_id")
    if not admin_id:
        raise HTTPException(
            status_code=403,
            detail="Administrator identity required",
        )

    email = normalize_email(payload.email)
    full_name = payload.full_name.strip()

    if len(full_name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Full name is required",
        )

    now = utc_now()
    created_at = now.isoformat()
    expires_at = (now + timedelta(hours=24)).isoformat()

    invitation_id = str(uuid4())

    # Never store the raw token in the database.
    secret_token = secrets.token_urlsafe(32)
    hashed_token = token_digest(secret_token)

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        existing_user = conn.execute("""
            SELECT user_id
            FROM users
            WHERE lower(email) = ?
            LIMIT 1
        """, (email,)).fetchone()

        if existing_user is not None:
            raise HTTPException(
                status_code=409,
                detail="An account already uses this email",
            )

        existing_invitation = conn.execute("""
            SELECT invitation_id
            FROM nurse_invitations
            WHERE email = ?
              AND accepted_at IS NULL
              AND revoked_at IS NULL
              AND expires_at > ?
            LIMIT 1
        """, (email, created_at)).fetchone()

        if existing_invitation is not None:
            raise HTTPException(
                status_code=409,
                detail="An active invitation already exists",
            )

        try:
            conn.execute("""
                INSERT INTO nurse_invitations (
                    invitation_id,
                    email,
                    full_name,
                    token_hash,
                    invited_by_user_id,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                invitation_id,
                email,
                full_name,
                hashed_token,
                admin_id,
                created_at,
                expires_at,
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Could not create invitation",
            )

    # Development-only delivery:
    # Copy this token from the backend terminal.
    print(
        f"\n[LOCAL DEV NURSE INVITE] "
        f"EMAIL={email} TOKEN={secret_token}\n",
        flush=True,
    )

    return {
        "invitation_id": invitation_id,
        "email": email,
        "full_name": full_name,
        "expires_at": expires_at,
        "status": "pending",
    }


@router.post("/auth/nurse-invitations/accept", status_code=201)
def accept_nurse_invitation(
    payload: NurseInvitationAccept,
    _origin=Depends(check_request_origin),
):
    hashed_token = token_digest(payload.token)
    now = utc_now()
    accepted_at = now.isoformat()

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        invitation = conn.execute("""
            SELECT
                invitation_id,
                email,
                full_name,
                expires_at,
                accepted_at,
                revoked_at
            FROM nurse_invitations
            WHERE token_hash = ?
            LIMIT 1
        """, (hashed_token,)).fetchone()

        if invitation is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired invitation",
            )

        expires_at = datetime.fromisoformat(
            invitation["expires_at"]
        )

        if (
            invitation["accepted_at"] is not None
            or invitation["revoked_at"] is not None
            or expires_at <= now
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired invitation",
            )

        existing = conn.execute("""
            SELECT user_id
            FROM users
            WHERE lower(email) = ?
            LIMIT 1
        """, (invitation["email"],)).fetchone()

        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="An account already uses this email",
            )

        user_id = str(uuid4())
        password_hash = password_hasher.hash(payload.password)

        try:
            conn.execute("""
                INSERT INTO users (
                    user_id,
                    patient_id,
                    doctor_id,
                    email,
                    password_hash,
                    role,
                    is_active,
                    created_at
                )
                VALUES (?, NULL, NULL, ?, ?, 'nurse', 1, ?)
            """, (
                user_id,
                invitation["email"],
                password_hash,
                accepted_at,
            ))

            conn.execute("""
                INSERT INTO nurse_profiles (
                    user_id,
                    full_name,
                    created_at
                )
                VALUES (?, ?, ?)
            """, (
                user_id,
                invitation["full_name"],
                accepted_at,
            ))

            conn.execute("""
                UPDATE nurse_invitations
                SET accepted_at = ?,
                    accepted_user_id = ?
                WHERE invitation_id = ?
            """, (
                accepted_at,
                user_id,
                invitation["invitation_id"],
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Unable to activate nurse account",
            )

    return {
        "message": "Nurse account created successfully",
        "role": "nurse",
        "email": invitation["email"],
    }
