
import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3

from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.core.database import get_db
from app.routers.appointments import check_request_origin


router = APIRouter(
    prefix="/auth/register",
    tags=["Patient Registration"],
)

hasher = PasswordHasher()

OTP_LIFETIME = timedelta(minutes=5)
OTP_COOLDOWN = timedelta(seconds=60)
OTP_WINDOW = timedelta(hours=1)
MAX_SENDS = 5
MAX_ATTEMPTS = 5

GENERIC_MESSAGE = (
    "If registration is available for this email, "
    "a verification code will be sent."
)


class RegisterStart(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class VerifyOTP(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^[0-9]{6}$")


class ResendOTP(BaseModel):
    email: EmailStr


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    return datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )


def signing_key():
    key = os.environ.get("OTP_SIGNING_KEY", "")
    if len(key) < 32:
        raise RuntimeError(
            "OTP_SIGNING_KEY must contain at least 32 characters"
        )
    return key.encode("utf-8")


def otp_digest(email, code):
    message = f"{email}:{code}".encode("utf-8")
    return hmac.new(
        signing_key(),
        message,
        hashlib.sha256,
    ).hexdigest()


def create_otp():
    return f"{secrets.randbelow(1000000):06d}"


def email_normalize(email):
    return str(email).strip().lower()


def send_otp_email(email, code):
    mode = os.environ.get("OTP_DELIVERY_MODE", "").lower()

    if mode == "console":
        if os.environ.get("APP_ENV") != "development":
            raise RuntimeError(
                "Console OTP delivery is development-only"
            )

        print(
            f"[LOCAL DEV OTP] {email}: {code}",
            flush=True,
        )
        return

    if mode != "smtp":
        raise RuntimeError(
            "Configure OTP_DELIVERY_MODE as smtp "
            "or development console mode"
        )

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "465"))
    username = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM")

    if not all([host, username, password, sender]):
        raise RuntimeError("SMTP configuration is incomplete")

    message = EmailMessage()
    message["Subject"] = "Verify your hospital account"
    message["From"] = sender
    message["To"] = email

    message.set_content(
        f"Your verification code is {code}.\n\n"
        "It expires in 5 minutes.\n"
        "Do not share this code."
    )

    with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)


def existing_user(conn, email):
    return conn.execute("""
        SELECT 1
        FROM users
        WHERE lower(email) = ?
        LIMIT 1
    """, (email,)).fetchone() is not None


def check_send_limit(pending, now):
    if pending is None:
        return 1, now.isoformat()

    last_sent = parse_time(pending["last_sent_at"])

    if now - last_sent < OTP_COOLDOWN:
        raise HTTPException(
            status_code=429,
            detail="Please wait before requesting another code",
        )

    window_start = parse_time(
        pending["window_started_at"]
    )

    if now - window_start >= OTP_WINDOW:
        return 1, now.isoformat()

    if pending["send_count"] >= MAX_SENDS:
        raise HTTPException(
            status_code=429,
            detail="Too many codes requested. Try again later",
        )

    return pending["send_count"] + 1, pending["window_started_at"]


def issue_code(conn, email, name, password_hash, pending):
    now = utc_now()
    count, window_start = check_send_limit(pending, now)

    code = create_otp()

    conn.execute("""
        INSERT INTO pending_patient_registrations (
            email,
            full_name,
            password_hash,
            otp_hash,
            otp_expires_at,
            attempts,
            send_count,
            window_started_at,
            last_sent_at,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            full_name = excluded.full_name,
            password_hash = excluded.password_hash,
            otp_hash = excluded.otp_hash,
            otp_expires_at = excluded.otp_expires_at,
            attempts = 0,
            send_count = excluded.send_count,
            window_started_at = excluded.window_started_at,
            last_sent_at = excluded.last_sent_at
    """, (
        email,
        name,
        password_hash,
        otp_digest(email, code),
        (now + OTP_LIFETIME).isoformat(),
        count,
        window_start,
        now.isoformat(),
        now.isoformat(),
    ))

    # SMTP failures roll back the pending code update.
    send_otp_email(email, code)


@router.post("/start")
def start_registration(
    payload: RegisterStart,
    _origin=Depends(check_request_origin),
):
    email = email_normalize(payload.email)
    full_name = " ".join(payload.full_name.split())

    if len(full_name) < 2:
        raise HTTPException(422, "Enter your full name")

    # Argon2 hashes the password before temporary storage.
    password_hash = hasher.hash(payload.password)

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        if existing_user(conn, email):
            return {"message": GENERIC_MESSAGE}

        pending = conn.execute("""
            SELECT *
            FROM pending_patient_registrations
            WHERE email = ?
        """, (email,)).fetchone()

        issue_code(
            conn, email, full_name, password_hash, pending
        )
        conn.commit()

    return {
        "message": GENERIC_MESSAGE,
        "expires_in_seconds": 300,
    }


@router.post("/resend")
def resend_registration_otp(
    payload: ResendOTP,
    _origin=Depends(check_request_origin),
):
    email = email_normalize(payload.email)

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        if existing_user(conn, email):
            return {"message": GENERIC_MESSAGE}

        pending = conn.execute("""
            SELECT *
            FROM pending_patient_registrations
            WHERE email = ?
        """, (email,)).fetchone()

        if pending is None:
            return {"message": GENERIC_MESSAGE}

        issue_code(
            conn,
            email,
            pending["full_name"],
            pending["password_hash"],
            pending,
        )
        conn.commit()

    return {"message": GENERIC_MESSAGE}


@router.post("/verify", status_code=201)
def verify_registration(
    payload: VerifyOTP,
    _origin=Depends(check_request_origin),
):
    email = email_normalize(payload.email)

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        pending = conn.execute("""
            SELECT *
            FROM pending_patient_registrations
            WHERE email = ?
        """, (email,)).fetchone()

        if pending is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired verification code",
            )

        if pending["attempts"] >= MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Request a new code",
            )

        if parse_time(pending["otp_expires_at"]) <= utc_now():
            raise HTTPException(
                status_code=400,
                detail="Verification code expired. Request a new code",
            )

        expected_hash = pending["otp_hash"]
        supplied_hash = otp_digest(email, payload.otp)

        if not hmac.compare_digest(
            expected_hash, supplied_hash
        ):
            conn.execute("""
                UPDATE pending_patient_registrations
                SET attempts = attempts + 1
                WHERE email = ?
            """, (email,))
            conn.commit()

            raise HTTPException(
                status_code=400,
                detail="Invalid or expired verification code",
            )

        if existing_user(conn, email):
            raise HTTPException(
                status_code=409,
                detail="Unable to complete registration",
            )

        patient_id = str(uuid4())
        user_id = str(uuid4())

        try:
            conn.execute("""
                INSERT INTO patients (
                    patient_id,
                    full_name,
                    email
                )
                VALUES (?, ?, ?)
            """, (
                patient_id,
                pending["full_name"],
                email,
            ))

            conn.execute("""
                INSERT INTO users (
                    user_id,
                    patient_id,
                    email,
                    password_hash,
                    role,
                    is_active
                )
                VALUES (?, ?, ?, ?, 'patient', 1)
            """, (
                user_id,
                patient_id,
                email,
                pending["password_hash"],
            ))

            conn.execute("""
                DELETE FROM pending_patient_registrations
                WHERE email = ?
            """, (email,))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Unable to complete registration",
            )

    return {
        "message": "Email verified. Your account is ready.",
        "role": "patient",
    }
