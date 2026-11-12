
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import tickets


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    db_path = tmp_path / "ticket_security.db"

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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO queries
        (ticket_id, patient_id, category, question)
        VALUES
        ('ticket-b', 'patient-b', 'billing',
         'Question from patient B');
    """)
    conn.close()

    def test_get_db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(tickets, "get_db", test_get_db)

    app.dependency_overrides[tickets.require_patient] = lambda: {
        "patient_id": "patient-a",
        "role": "patient",
    }

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(tickets.require_patient, None)


def test_patient_cannot_read_another_ticket(test_client):
    response = test_client.get("/my/queries/ticket-b")
    assert response.status_code == 404


def test_patient_cannot_list_another_ticket(test_client):
    response = test_client.get("/my/queries")
    assert response.status_code == 200
    assert response.json() == []
