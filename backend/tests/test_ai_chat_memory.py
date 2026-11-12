
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import (
    ai_chat_memory,
    medical_documents,
)
from app.routers.patient_ai import ChatResponse

from scripts.create_ai_chat_memory import (
    create_ai_chat_tables,
)


# ============================================================
# ISOLATED TEST DATABASE
# ============================================================

@pytest.fixture
def chat_client(tmp_path, monkeypatch):
    db_path = tmp_path / "ai_chat_test.db"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE patients (
                patient_id TEXT PRIMARY KEY
            );

            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                patient_id TEXT,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );
        """)

        conn.executemany(
            "INSERT INTO patients VALUES (?)",
            [
                ("patient-a",),
                ("patient-b",),
            ],
        )

        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?)",
            [
                ("user-a", "patient-a", "patient", 1),
                ("user-b", "patient-b", "patient", 1),
            ],
        )

        create_ai_chat_tables(conn)
        conn.commit()

    current = {
        "user": {
            "user_id": "user-a",
            "patient_id": "patient-a",
            "role": "patient",
        }
    }

    ai_calls = []

    def fake_ai_response(message):
        ai_calls.append(message)

        return ChatResponse(
            reply=(
                "You can review your appointments "
                "in the Patient Portal."
            ),
            intent="appointments",
            requires_human=False,
            sources=[],
        )

    monkeypatch.setattr(
        ai_chat_memory,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        medical_documents,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        medical_documents,
        "get_current_user",
        lambda token: current["user"],
    )

    monkeypatch.setattr(
        ai_chat_memory,
        "generate_patient_ai_response",
        fake_ai_response,
    )

    # Keep appointment lookups inside the isolated test.
    # Individual appointment tests can override this mock.
    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        lambda patient_id, limit=10: [],
    )

    app.dependency_overrides[
        ai_chat_memory.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            client.cookies.set(
                "hospital_session",
                "fictional-test-session",
            )

            yield client, connect, current, ai_calls

    finally:
        app.dependency_overrides.pop(
            ai_chat_memory.check_request_origin,
            None,
        )


# ============================================================
# HELPERS
# ============================================================

def create_chat(client):
    return client.post(
        "/patient/ai/conversations"
    )


def send_message(client, conversation_id, message):
    return client.post(
        f"/patient/ai/conversations/"
        f"{conversation_id}/messages",
        json={"message": message},
    )


def switch_to_patient_b(current):
    current["user"] = {
        "user_id": "user-b",
        "patient_id": "patient-b",
        "role": "patient",
    }


# ============================================================
# TEST 1 — CREATE CONVERSATION
# ============================================================

def test_patient_can_create_conversation(chat_client):
    client, connect, _, _ = chat_client

    response = create_chat(client)

    assert response.status_code == 201

    data = response.json()

    assert data["conversation_id"]
    assert data["title"] == "New Chat"

    with connect() as conn:
        conversation = conn.execute("""
            SELECT *
            FROM ai_conversations
            WHERE conversation_id = ?
        """, (
            data["conversation_id"],
        )).fetchone()

    assert conversation is not None
    assert conversation["patient_id"] == "patient-a"
    assert conversation["owner_user_id"] == "user-a"


# ============================================================
# TEST 2 — CONVERSATION LIST IS PATIENT-SPECIFIC
# ============================================================

def test_patients_see_only_their_own_chats(chat_client):
    client, _, current, _ = chat_client

    created = create_chat(client)

    assert created.status_code == 201

    list_a = client.get(
        "/patient/ai/conversations"
    )

    assert list_a.status_code == 200
    assert list_a.json()["total"] == 1

    switch_to_patient_b(current)

    list_b = client.get(
        "/patient/ai/conversations"
    )

    assert list_b.status_code == 200
    assert list_b.json()["total"] == 0
    assert list_b.json()["conversations"] == []


# ============================================================
# TEST 3 — SAVE USER AND ASSISTANT MESSAGES
# ============================================================

def test_chat_messages_are_saved(chat_client):
    client, connect, _, ai_calls = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        "Where are my appointments?",
    )

    assert response.status_code == 201

    result = response.json()

    assert result["user_message"]["role"] == "user"
    assert result["assistant_message"]["role"] == "assistant"
    assert result["intent"] == "appointments"

    # Appointment questions now use local tools,
    # not the external AI service.
    assert ai_calls == []

    assert "no upcoming booked appointments" in (
        result["assistant_message"]["content"].lower()
    )

    with connect() as conn:
        messages = conn.execute("""
            SELECT role, content
            FROM ai_chat_messages
            WHERE conversation_id = ?
            ORDER BY rowid
        """, (
            conversation_id,
        )).fetchall()

    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


# ============================================================
# TEST 4 — RETRIEVE PREVIOUS MESSAGE HISTORY
# ============================================================

def test_patient_can_read_previous_messages(
    chat_client,
):
    client, _, _, _ = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    assert send_message(
        client,
        conversation_id,
        "First question",
    ).status_code == 201

    assert send_message(
        client,
        conversation_id,
        "Second question",
    ).status_code == 201

    response = client.get(
        f"/patient/ai/conversations/{conversation_id}"
    )

    assert response.status_code == 200

    messages = response.json()["messages"]

    assert len(messages) == 4

    assert [m["role"] for m in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    assert messages[0]["content"] == "First question"
    assert messages[2]["content"] == "Second question"


# ============================================================
# TEST 5 — OTHER PATIENT CANNOT READ CHAT
# ============================================================

def test_other_patient_cannot_read_conversation(
    chat_client,
):
    client, _, current, _ = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    switch_to_patient_b(current)

    response = client.get(
        f"/patient/ai/conversations/{conversation_id}"
    )

    assert response.status_code == 404


# ============================================================
# TEST 6 — OTHER PATIENT CANNOT SEND TO CHAT
# ============================================================

def test_other_patient_cannot_send_message(
    chat_client,
):
    client, connect, current, ai_calls = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    switch_to_patient_b(current)

    response = send_message(
        client,
        conversation_id,
        "Unauthorized message",
    )

    assert response.status_code == 404

    # Ownership must be checked BEFORE calling AI.
    assert ai_calls == []

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*)
            FROM ai_chat_messages
        """).fetchone()[0]

    assert count == 0


# ============================================================
# TEST 7 — OTHER PATIENT CANNOT DELETE CHAT
# ============================================================

def test_other_patient_cannot_delete_conversation(
    chat_client,
):
    client, _, current, _ = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    switch_to_patient_b(current)

    response = client.delete(
        f"/patient/ai/conversations/{conversation_id}"
    )

    assert response.status_code == 404

    # Original owner can still see the conversation.
    current["user"] = {
        "user_id": "user-a",
        "patient_id": "patient-a",
        "role": "patient",
    }

    original = client.get(
        f"/patient/ai/conversations/{conversation_id}"
    )

    assert original.status_code == 200


# ============================================================
# TEST 8 — DELETE CHAT AND ALL SAVED MESSAGES
# ============================================================

def test_deleting_chat_deletes_its_messages(
    chat_client,
):
    client, connect, _, _ = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    assert send_message(
        client,
        conversation_id,
        "Test message",
    ).status_code == 201

    response = client.delete(
        f"/patient/ai/conversations/{conversation_id}"
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True

    with connect() as conn:
        conversation_count = conn.execute("""
            SELECT COUNT(*)
            FROM ai_conversations
            WHERE conversation_id = ?
        """, (conversation_id,)).fetchone()[0]

        message_count = conn.execute("""
            SELECT COUNT(*)
            FROM ai_chat_messages
            WHERE conversation_id = ?
        """, (conversation_id,)).fetchone()[0]

    assert conversation_count == 0
    assert message_count == 0


# ============================================================
# TEST 9 — LOGIN REQUIRED
# ============================================================

def test_chat_memory_requires_login(chat_client):
    client, _, _, _ = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    client.cookies.clear()

    responses = [
        client.get("/patient/ai/conversations"),
        client.post("/patient/ai/conversations"),
        client.get(
            f"/patient/ai/conversations/{conversation_id}"
        ),
        client.post(
            f"/patient/ai/conversations/"
            f"{conversation_id}/messages",
            json={"message": "hello"},
        ),
        client.delete(
            f"/patient/ai/conversations/{conversation_id}"
        ),
    ]

    assert all(
        response.status_code == 401
        for response in responses
    )


# ============================================================
# TEST 10 — INACTIVE PATIENT ACCOUNT BLOCKED
# ============================================================

def test_inactive_patient_cannot_access_chat(
    chat_client,
):
    client, connect, _, _ = chat_client

    with connect() as conn:
        conn.execute("""
            UPDATE users
            SET is_active = 0
            WHERE user_id = 'user-a'
        """)
        conn.commit()

    listing = client.get(
        "/patient/ai/conversations"
    )

    creation = create_chat(client)

    assert listing.status_code == 403
    assert creation.status_code == 403


# ============================================================
# TEST 11 — SESSION IDENTITY MISMATCH BLOCKED
# ============================================================

def test_session_identity_mismatch_is_rejected(
    chat_client,
):
    client, _, current, _ = chat_client

    # user-a belongs to patient-a,
    # but the session claims patient-b.
    current["user"] = {
        "user_id": "user-a",
        "patient_id": "patient-b",
        "role": "patient",
    }

    listing = client.get(
        "/patient/ai/conversations"
    )

    creation = create_chat(client)

    assert listing.status_code == 403
    assert creation.status_code == 403


# ============================================================
# TEST 12 — INVALID MESSAGE CONTENT REJECTED
# ============================================================

def test_empty_and_oversized_messages_rejected(
    chat_client,
):
    client, connect, _, ai_calls = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    empty = send_message(
        client,
        conversation_id,
        "   ",
    )

    oversized = send_message(
        client,
        conversation_id,
        "x" * 2001,
    )

    assert empty.status_code == 422
    assert oversized.status_code == 422

    assert ai_calls == []

    with connect() as conn:
        count = conn.execute("""
            SELECT COUNT(*)
            FROM ai_chat_messages
        """).fetchone()[0]

    assert count == 0


def test_ai_lookup_uses_authenticated_patient_id(
    chat_client, monkeypatch
):
    client, _, _, ai_calls = chat_client
    lookup_calls = []

    def fake_lookup(patient_id, limit=10):
        lookup_calls.append((patient_id, limit))
        return []

    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        fake_lookup,
    )

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        "What are my appointments?",
    )

    assert response.status_code == 201
    assert lookup_calls == [("patient-a", 10)]
    assert ai_calls == []
    assert response.json()["intent"] == "appointments"
    assert "no upcoming" in (
        response.json()["assistant_message"]["content"].lower()
    )


def test_ai_lookup_uses_second_patients_identity(
    chat_client, monkeypatch
):
    client, _, current, ai_calls = chat_client
    lookup_calls = []

    def fake_lookup(patient_id, limit=10):
        lookup_calls.append(patient_id)
        return []

    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        fake_lookup,
    )

    switch_to_patient_b(current)

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        "When is my next appointment?",
    )

    assert response.status_code == 201
    assert lookup_calls == ["patient-b"]
    assert ai_calls == []


def test_other_patient_cannot_trigger_appointment_lookup(
    chat_client, monkeypatch
):
    client, _, current, ai_calls = chat_client
    lookup_calls = []

    def fake_lookup(patient_id, limit=10):
        lookup_calls.append(patient_id)
        return []

    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        fake_lookup,
    )

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    switch_to_patient_b(current)

    response = send_message(
        client,
        conversation_id,
        "What are my appointments?",
    )

    assert response.status_code == 404
    assert lookup_calls == []
    assert ai_calls == []


# ============================================================
# AI BOOKING NAVIGATION TESTS
# ============================================================

def test_booking_question_uses_local_instructions(
    chat_client, monkeypatch
):
    client, _, _, ai_calls = chat_client
    lookup_calls = []

    def fake_lookup(patient_id, limit=10):
        lookup_calls.append(patient_id)
        return []

    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        fake_lookup,
    )

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        "How do I schedule a new appointment?",
    )

    assert response.status_code == 201

    data = response.json()
    reply = data["assistant_message"]["content"]

    assert "Find Doctors" in reply
    assert data["intent"] == "appointments"
    assert lookup_calls == []
    assert ai_calls == []


def test_book_appointment_question_is_recognized(
    chat_client
):
    client, _, _, ai_calls = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        "How can I book an appointment?",
    )

    assert response.status_code == 201
    assert "Find Doctors" in (
        response.json()["assistant_message"]["content"]
    )
    assert ai_calls == []


def test_medical_question_bypasses_booking_shortcut(
    chat_client
):
    client, _, _, ai_calls = chat_client

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    message = (
        "How do I schedule a new appointment "
        "for chest pain?"
    )

    response = send_message(
        client,
        conversation_id,
        message,
    )

    assert response.status_code == 201

    # The medical question must be passed to the
    # existing safety-aware response handler.
    assert ai_calls == [message]


# ============================================================
# APPOINTMENT QUESTION HANDLING
# ============================================================

@pytest.mark.parametrize(
    "question,expected_limit",
    [
        ("When is my next appointment?", 1),
        ("Show all my upcoming appointments", 20),
        ("What are my appointments?", 10),
    ],
)
def test_ai_appointment_query_limits(
    chat_client,
    monkeypatch,
    question,
    expected_limit,
):
    client, _, _, ai_calls = chat_client

    lookup_calls = []

    def fake_lookup(patient_id, limit=10):
        lookup_calls.append({
            "patient_id": patient_id,
            "limit": limit,
        })
        return []

    monkeypatch.setattr(
        ai_chat_memory,
        "get_upcoming_appointments",
        fake_lookup,
    )

    conversation_id = create_chat(
        client
    ).json()["conversation_id"]

    response = send_message(
        client,
        conversation_id,
        question,
    )

    assert response.status_code == 201

    assert lookup_calls == [
        {
            "patient_id": "patient-a",
            "limit": expected_limit,
        }
    ]

    assert response.json()["intent"] == "appointments"

    # Appointment questions must use local tools.
    # They must not send private records to Groq.
    assert ai_calls == []
