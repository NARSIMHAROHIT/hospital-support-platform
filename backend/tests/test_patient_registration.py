
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import registration


@pytest.fixture
def registration_client(tmp_path, monkeypatch):
    db_path = tmp_path / "registration.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE patients (
                patient_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            );

            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                patient_id TEXT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );

            CREATE TABLE pending_patient_registrations (
                email TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                otp_hash TEXT NOT NULL,
                otp_expires_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                send_count INTEGER NOT NULL DEFAULT 1,
                window_started_at TEXT NOT NULL,
                last_sent_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

    monkeypatch.setattr(
        registration, "get_db", connect
    )
    monkeypatch.setattr(
        registration, "create_otp", lambda: "123456"
    )
    monkeypatch.setattr(
        registration, "signing_key",
        lambda: b"test-key-for-local-registration-tests-only"
    )
    monkeypatch.setattr(
        registration, "send_otp_email",
        lambda email, code: None
    )

    app.dependency_overrides[
        registration.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect
    finally:
        app.dependency_overrides.pop(
            registration.check_request_origin, None
        )


def register(client):
    return client.post(
        "/auth/register/start",
        json={
            "full_name": "Test Patient",
            "email": "newpatient@example.com",
            "password": "StrongPassword123!",
        },
    )


def test_registration_requires_otp(registration_client):
    client, connect = registration_client

    response = register(client)

    assert response.status_code == 200

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM users
        """).fetchone()[0]

        pending = conn.execute("""
            SELECT *
            FROM pending_patient_registrations
        """).fetchone()

    assert count == 0
    assert pending is not None
    assert pending["otp_hash"] != "123456"


def test_correct_otp_creates_patient(registration_client):
    client, connect = registration_client

    register(client)

    response = client.post(
        "/auth/register/verify",
        json={
            "email": "newpatient@example.com",
            "otp": "123456",
        },
    )

    assert response.status_code == 201

    with connect() as conn:
        user = conn.execute("""
            SELECT role, is_active, password_hash
            FROM users
        """).fetchone()

        patient = conn.execute("""
            SELECT full_name FROM patients
        """).fetchone()

    assert user["role"] == "patient"
    assert user["is_active"] == 1
    assert user["password_hash"] != "StrongPassword123!"
    assert patient["full_name"] == "Test Patient"


def test_wrong_otp_is_rejected(registration_client):
    client, connect = registration_client

    register(client)

    response = client.post(
        "/auth/register/verify",
        json={
            "email": "newpatient@example.com",
            "otp": "000000",
        },
    )

    assert response.status_code == 400

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM users
        """).fetchone()[0]

        attempts = conn.execute("""
            SELECT attempts
            FROM pending_patient_registrations
        """).fetchone()["attempts"]

    assert count == 0
    assert attempts == 1


def test_immediate_resend_is_limited(registration_client):
    client, _ = registration_client

    register(client)

    response = client.post(
        "/auth/register/resend",
        json={"email": "newpatient@example.com"},
    )

    assert response.status_code == 429
