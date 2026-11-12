
import re
import sqlite3

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.main import app
from app.routers import nurse_invitations
from scripts.create_nurse_invitations import create_nurse_tables


TEST_PASSWORD = "StrongDemoPassword123!"


@pytest.fixture
def nurse_client(tmp_path, monkeypatch):
    db_path = tmp_path / "nurse_test.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                patient_id TEXT,
                doctor_id TEXT,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        conn.execute("""
            INSERT INTO users (
                user_id, email, password_hash,
                role, is_active, created_at
            )
            VALUES (
                'admin1', 'admin@example.test', 'test-hash',
                'admin', 1, '2026-01-01T00:00:00+00:00'
            )
        """)

        create_nurse_tables(conn)
        conn.commit()

    monkeypatch.setattr(
        nurse_invitations,
        "get_db",
        connect,
    )

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "NURSE_INVITE_DELIVERY_MODE", "console"
    )

    app.dependency_overrides[
        nurse_invitations.require_admin
    ] = lambda: {
        "user_id": "admin1",
        "role": "admin",
    }

    app.dependency_overrides[
        nurse_invitations.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            yield client, connect
    finally:
        app.dependency_overrides.pop(
            nurse_invitations.require_admin, None
        )
        app.dependency_overrides.pop(
            nurse_invitations.check_request_origin, None
        )


def invite(client, email="nurse@example.test"):
    return client.post(
        "/admin/nurse-invitations",
        json={
            "email": email,
            "full_name": "Taylor Reed",
        },
    )


def get_token(capsys):
    output = capsys.readouterr().out
    match = re.search(r"TOKEN=([A-Za-z0-9_-]+)", output)

    assert match is not None
    return match.group(1)


def accept(client, token, password=TEST_PASSWORD):
    return client.post(
        "/auth/nurse-invitations/accept",
        json={
            "token": token,
            "password": password,
        },
    )


def test_admin_can_issue_invitation(
    nurse_client, capsys
):
    client, connect = nurse_client

    response = invite(client)

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert "token" not in response.json()

    token = get_token(capsys)

    with connect() as conn:
        stored = conn.execute("""
            SELECT token_hash
            FROM nurse_invitations
        """).fetchone()

    assert stored["token_hash"] != token
    assert len(stored["token_hash"]) == 64


def test_nurse_can_accept_invitation(
    nurse_client, capsys
):
    client, connect = nurse_client

    assert invite(client).status_code == 201
    token = get_token(capsys)

    response = accept(client, token)

    assert response.status_code == 201
    assert response.json()["role"] == "nurse"
    assert "password" not in response.json()

    with connect() as conn:
        nurse = conn.execute("""
            SELECT user_id, email, role,
                   password_hash, is_active
            FROM users
            WHERE email = 'nurse@example.test'
        """).fetchone()

        profile = conn.execute("""
            SELECT full_name
            FROM nurse_profiles
            WHERE user_id = ?
        """, (nurse["user_id"],)).fetchone()

        invitation = conn.execute("""
            SELECT accepted_at
            FROM nurse_invitations
        """).fetchone()

    assert nurse["role"] == "nurse"
    assert nurse["is_active"] == 1
    assert profile["full_name"] == "Taylor Reed"
    assert invitation["accepted_at"] is not None

    assert PasswordHasher().verify(
        nurse["password_hash"],
        TEST_PASSWORD,
    )


def test_invitation_cannot_be_used_twice(
    nurse_client, capsys
):
    client, _ = nurse_client

    assert invite(client).status_code == 201
    token = get_token(capsys)

    assert accept(client, token).status_code == 201
    assert accept(client, token).status_code == 400


def test_expired_invitation_is_rejected(
    nurse_client, capsys
):
    client, connect = nurse_client

    assert invite(client).status_code == 201
    token = get_token(capsys)

    with connect() as conn:
        conn.execute("""
            UPDATE nurse_invitations
            SET expires_at = '2000-01-01T00:00:00+00:00'
        """)
        conn.commit()

    assert accept(client, token).status_code == 400


def test_duplicate_pending_invitation_is_rejected(
    nurse_client,
):
    client, _ = nurse_client

    assert invite(client).status_code == 201
    assert invite(client).status_code == 409


def test_existing_user_email_is_rejected(
    nurse_client,
):
    client, _ = nurse_client

    assert invite(
        client, "admin@example.test"
    ).status_code == 409


def test_short_password_is_rejected(
    nurse_client, capsys
):
    client, _ = nurse_client

    assert invite(client).status_code == 201
    token = get_token(capsys)

    response = accept(client, token, "short")

    assert response.status_code == 422


def test_unknown_token_is_rejected(nurse_client):
    client, _ = nurse_client

    response = accept(
        client,
        "this-is-an-invalid-invitation-token",
    )

    assert response.status_code == 400


def test_delivery_must_be_configured(
    nurse_client, monkeypatch
):
    client, _ = nurse_client

    monkeypatch.setenv(
        "NURSE_INVITE_DELIVERY_MODE", "smtp"
    )

    assert invite(client).status_code == 503


def test_invitation_requires_admin(nurse_client):
    client, _ = nurse_client

    app.dependency_overrides.pop(
        nurse_invitations.require_admin,
        None,
    )

    response = invite(client)

    assert response.status_code in (401, 403)
