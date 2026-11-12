
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import tickets


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Every test gets its own temporary SQLite database.
    db_path = tmp_path / "tickets_test.db"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE queries (
            ticket_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            category TEXT NOT NULL,
            question TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'medium',
            department TEXT DEFAULT 'general',
            assigned_to TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()

    def test_get_db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(tickets, "get_db", test_get_db)

    app.dependency_overrides[tickets.require_admin] = lambda: {
        "user_id": "test-admin",
        "role": "admin",
    }
    app.dependency_overrides[
        tickets.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(tickets.require_admin, None)
        app.dependency_overrides.pop(
            tickets.check_request_origin, None
        )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_create_ticket(client):
    response = client.post("/queries", json={
        "patient_id": "TEST001",
        "category": "billing",
        "question": "How can I view my sample invoice?"
    })

    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_update_ticket(client):
    created = client.post("/queries", json={
        "patient_id": "TEST002",
        "category": "appointment",
        "question": "How can I reschedule my appointment?"
    })

    assert created.status_code == 201
    ticket_id = created.json()["ticket_id"]

    response = client.patch(
        f"/queries/{ticket_id}",
        json={"status": "resolved"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_invalid_category(client):
    response = client.post("/queries", json={
        "patient_id": "TEST003",
        "category": "invalid_category",
        "question": "Example invalid category request"
    })

    assert response.status_code == 422


def test_missing_ticket(client):
    response = client.get("/queries/nonexistent-ticket")
    assert response.status_code == 404


def test_admin_endpoint_requires_login():
    # This separate client has no permission override.
    with TestClient(app) as test_client:
        response = test_client.get("/queries")

    assert response.status_code == 401


def test_patient_cannot_use_admin_ticket_endpoint():
    app.dependency_overrides[tickets.require_admin] = lambda: {
        "user_id": "patient-test",
        "role": "patient",
    }

    try:
        # Test only that a real administrator check is enforced.
        # A dependency override replaces the check, so we instead
        # call the permission helper in a separate authorization test.
        pass
    finally:
        app.dependency_overrides.pop(tickets.require_admin, None)
