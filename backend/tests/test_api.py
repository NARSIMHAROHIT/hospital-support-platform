
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_create_ticket():
    response = client.post("/queries", json={
        "patient_id": "TEST001",
        "category": "billing",
        "question": "How can I view my sample invoice?"
    })

    assert response.status_code == 201
    assert response.json()["status"] == "open"

def test_update_ticket():
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

def test_invalid_category():
    response = client.post("/queries", json={
        "patient_id": "TEST003",
        "category": "invalid_category",
        "question": "Example invalid category request"
    })

    assert response.status_code == 422

def test_missing_ticket():
    response = client.get("/queries/nonexistent-ticket")
    assert response.status_code == 404
