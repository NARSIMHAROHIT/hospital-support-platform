
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import (
    clinical_patients,
    doctor_clinical_notes,
    clinical_note_sharing,
)

from scripts.create_care_team import create_care_team_tables
from scripts.create_doctor_clinical_notes import (
    create_clinical_note_tables,
)
from scripts.create_note_releases import (
    create_note_release_tables,
)
from scripts.create_clinical_audit import (
    create_clinical_audit_tables,
)


# ============================================================
# TEST DATABASE AND AUTHENTICATION FIXTURE
# ============================================================

@pytest.fixture
def notes_client(tmp_path, monkeypatch):
    database_path = tmp_path / "clinical_notes.db"

    def connect():
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    with connect() as conn:
        conn.executescript("""
            CREATE TABLE patients (
                patient_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL
            );

            CREATE TABLE doctors (
                doctor_id TEXT PRIMARY KEY,
                is_active INTEGER NOT NULL,
                full_name TEXT NOT NULL
            );

            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                patient_id TEXT,
                doctor_id TEXT,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );

            CREATE TABLE doctor_slots (
                slot_id TEXT PRIMARY KEY,
                doctor_id TEXT,
                starts_at TEXT,
                ends_at TEXT
            );

            CREATE TABLE appointments (
                appointment_id TEXT PRIMARY KEY,
                patient_id TEXT,
                doctor_id TEXT,
                slot_id TEXT,
                status TEXT
            );
        """)

        # Create all required tables in the isolated
        # test database, including the new audit table.
        create_care_team_tables(conn)
        create_clinical_note_tables(conn)
        create_note_release_tables(conn)
        create_clinical_audit_tables(conn)

        conn.executemany(
            "INSERT INTO patients VALUES (?, ?)",
            [
                ("p1", "Alex Morgan"),
                ("p2", "Jamie Lee"),
            ],
        )

        conn.executemany("""
            INSERT INTO doctors (
                doctor_id,
                is_active,
                full_name
            )
            VALUES (?, ?, ?)
        """, [
            ("d1", 1, "Dr. Maya Patel"),
            ("d2", 1, "Dr. Jordan Lee"),
        ])

        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            [
                ("admin", None, None, "admin", 1),
                ("doc1", None, "d1", "doctor", 1),
                ("doc2", None, "d2", "doctor", 1),
                ("patient1", "p1", None, "patient", 1),
                ("nurse1", None, None, "nurse", 1),
            ],
        )

        conn.executemany("""
            INSERT INTO doctor_slots
            VALUES (?, ?, ?, ?)
        """, [
            (
                "s1",
                "d1",
                "2099-11-18T15:00:00+00:00",
                "2099-11-18T15:30:00+00:00",
            ),
            (
                "s2",
                "d2",
                "2099-11-19T15:00:00+00:00",
                "2099-11-19T15:30:00+00:00",
            ),
        ])

        conn.executemany("""
            INSERT INTO appointments
            VALUES (?, ?, ?, ?, ?)
        """, [
            ("a1", "p1", "d1", "s1", "booked"),
            ("a2", "p1", "d2", "s2", "booked"),
        ])

        conn.commit()

    current = {
        "user": {
            "user_id": "doc1",
            "doctor_id": "d1",
            "role": "doctor",
        }
    }

    # Redirect all three routers to the test database.
    monkeypatch.setattr(
        doctor_clinical_notes,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        clinical_patients,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        clinical_note_sharing,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        clinical_patients,
        "get_current_user",
        lambda token: current["user"],
    )

    app.dependency_overrides[
        doctor_clinical_notes.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            client.cookies.set(
                "hospital_session",
                "fictional-test-session",
            )
            yield client, connect, current

    finally:
        app.dependency_overrides.pop(
            doctor_clinical_notes.check_request_origin,
            None,
        )


# ============================================================
# TEST HELPERS
# ============================================================

def create_note(
    client,
    appointment_id="a1",
    patient_id="p1",
):
    return client.post(
        "/doctor/clinical-notes",
        json={
            "patient_id": patient_id,
            "appointment_id": appointment_id,
            "observations": (
                "Fictional patient reports fatigue."
            ),
            "assessment": "Demo assessment.",
            "treatment_plan": "Demo follow-up plan.",
        },
    )


def create_signed_demo_note(client):
    response = create_note(client)
    assert response.status_code == 201

    note_id = response.json()["note_id"]

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/sign"
    )
    assert response.status_code == 200

    return note_id


def audit_events(connect, actor_user_id=None):
    """Read audit entries from the isolated test database."""

    with connect() as conn:
        if actor_user_id is None:
            rows = conn.execute("""
                SELECT *
                FROM clinical_audit_events
                ORDER BY rowid
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT *
                FROM clinical_audit_events
                WHERE actor_user_id = ?
                ORDER BY rowid
            """, (actor_user_id,)).fetchall()

    return [dict(row) for row in rows]


def switch_to_second_doctor(current):
    current["user"] = {
        "user_id": "doc2",
        "doctor_id": "d2",
        "role": "doctor",
    }


def switch_to_patient(current, patient_id="p1", user_id="patient1"):
    current["user"] = {
        "user_id": user_id,
        "patient_id": patient_id,
        "role": "patient",
    }


# ============================================================
# ORIGINAL TESTS 1–25
# ============================================================

def test_doctor_can_create_draft(notes_client):
    client, connect, _ = notes_client

    response = create_note(client)

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert response.json()["patient_id"] == "p1"
    assert response.json()["author_user_id"] == "doc1"

    with connect() as conn:
        events = conn.execute("""
            SELECT event_type
            FROM doctor_note_events
        """).fetchall()

    assert [e["event_type"] for e in events] == ["created"]


def test_doctor_can_edit_own_draft(notes_client):
    client, connect, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.patch(
        f"/doctor/clinical-notes/{note_id}",
        json={
            "observations": "Updated fictional observations.",
            "assessment": "Updated fictional assessment.",
        },
    )

    assert response.status_code == 200
    assert response.json()["observations"] == (
        "Updated fictional observations."
    )

    with connect() as conn:
        events = conn.execute("""
            SELECT event_type
            FROM doctor_note_events
            ORDER BY created_at, rowid
        """).fetchall()

    assert [e["event_type"] for e in events] == [
        "created",
        "edited",
    ]


def test_doctor_can_sign_note(notes_client):
    client, _, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/sign"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "signed"
    assert response.json()["signed_at"] is not None


def test_signed_note_cannot_be_edited(notes_client):
    client, _, _ = notes_client

    note_id = create_signed_demo_note(client)

    response = client.patch(
        f"/doctor/clinical-notes/{note_id}",
        json={"observations": "Overwritten note"},
    )

    assert response.status_code == 409


def test_signed_note_accepts_addendum(notes_client):
    client, connect, _ = notes_client

    note_id = create_signed_demo_note(client)

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/addenda",
        json={
            "content": "Correction: fictional follow-up updated.",
        },
    )

    assert response.status_code == 201

    detail = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )

    assert detail.status_code == 200
    assert len(detail.json()["addenda"]) == 1

    with connect() as conn:
        events = conn.execute("""
            SELECT event_type
            FROM doctor_note_events
            ORDER BY created_at, rowid
        """).fetchall()

    assert [e["event_type"] for e in events] == [
        "created",
        "signed",
        "addendum_added",
    ]


def test_draft_cannot_have_addendum(notes_client):
    client, _, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/addenda",
        json={"content": "Correction"},
    )

    assert response.status_code == 409


def test_duplicate_note_is_rejected(notes_client):
    client, _, _ = notes_client

    assert create_note(client).status_code == 201
    assert create_note(client).status_code == 409


def test_other_doctor_cannot_use_wrong_appointment(
    notes_client,
):
    client, _, _ = notes_client

    response = create_note(
        client,
        appointment_id="a2",
    )

    assert response.status_code == 404


def test_other_doctor_cannot_read_draft(notes_client):
    client, _, current = notes_client

    note_id = create_note(client).json()["note_id"]
    switch_to_second_doctor(current)

    response = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )

    assert response.status_code == 404


def test_other_authorized_doctor_can_read_signed_note(
    notes_client,
):
    client, _, current = notes_client

    note_id = create_signed_demo_note(client)
    switch_to_second_doctor(current)

    response = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "signed"


def test_other_doctor_cannot_edit_signed_note(
    notes_client,
):
    client, _, current = notes_client

    note_id = create_signed_demo_note(client)
    switch_to_second_doctor(current)

    response = client.patch(
        f"/doctor/clinical-notes/{note_id}",
        json={"observations": "Unauthorized edit"},
    )

    assert response.status_code == 403


def test_cancelled_appointment_cannot_create_note(
    notes_client,
):
    client, connect, _ = notes_client

    with connect() as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'a1'
        """)

        conn.execute("""
            INSERT INTO care_team_assignments (
                assignment_id,
                patient_id,
                staff_user_id,
                assigned_by_user_id
            )
            VALUES (
                'assignment1',
                'p1',
                'doc1',
                'admin'
            )
        """)

        conn.commit()

    assert create_note(client).status_code == 409


def test_patient_cannot_use_doctor_note_api(
    notes_client,
):
    client, _, current = notes_client
    switch_to_patient(current)

    assert create_note(client).status_code == 403


def test_missing_session_is_rejected(notes_client):
    client, _, _ = notes_client

    client.cookies.clear()

    assert create_note(client).status_code == 401


def test_unknown_note_returns_404(notes_client):
    client, _, _ = notes_client

    response = client.get(
        "/doctor/clinical-notes/nonexistent-note"
    )

    assert response.status_code == 404


def test_authorized_doctor_lists_note_appointments(
    notes_client,
):
    client, _, _ = notes_client

    response = client.get(
        "/doctor/clinical-notes/patient/p1/appointments"
    )

    assert response.status_code == 200

    ids = [
        row["appointment_id"]
        for row in response.json()["appointments"]
    ]

    assert ids == ["a1"]


def test_other_doctor_sees_only_own_appointments(
    notes_client,
):
    client, _, current = notes_client

    switch_to_second_doctor(current)

    response = client.get(
        "/doctor/clinical-notes/patient/p1/appointments"
    )

    assert response.status_code == 200

    ids = [
        row["appointment_id"]
        for row in response.json()["appointments"]
    ]

    assert ids == ["a2"]


def test_cancelled_booking_removes_note_appointment_access(
    notes_client,
):
    client, connect, _ = notes_client

    with connect() as conn:
        conn.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = 'a1'
        """)
        conn.commit()

    response = client.get(
        "/doctor/clinical-notes/patient/p1/appointments"
    )

    assert response.status_code == 404


def test_draft_cannot_be_shared(notes_client):
    client, _, _ = notes_client

    response = create_note(client)
    assert response.status_code == 201

    note_id = response.json()["note_id"]

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    assert release.status_code == 409


def test_signed_note_is_private_by_default(
    notes_client,
):
    client, _, current = notes_client

    note_id = create_signed_demo_note(client)

    switch_to_patient(current)

    listing = client.get(
        "/clinical/note-sharing/my-notes"
    )

    detail = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    assert detail.status_code == 404


def test_patient_can_view_released_note(notes_client):
    client, _, current = notes_client

    note_id = create_signed_demo_note(client)

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    assert release.status_code == 200
    assert release.json()["released"] is True

    switch_to_patient(current)

    listing = client.get(
        "/clinical/note-sharing/my-notes"
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["notes"][0]["note_id"] == note_id

    assert listing.json()["notes"][0]["doctor_name"] == (
        "Dr. Maya Patel"
    )

    detail = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )

    assert detail.status_code == 200
    assert detail.json()["observations"] == (
        "Fictional patient reports fatigue."
    )
    assert detail.json()["assessment"] == "Demo assessment."
    assert detail.json()["treatment_plan"] == (
        "Demo follow-up plan."
    )


def test_other_patient_cannot_view_released_note(
    notes_client,
):
    client, connect, current = notes_client

    note_id = create_signed_demo_note(client)

    assert client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    ).status_code == 200

    with connect() as conn:
        conn.execute("""
            INSERT INTO users (
                user_id,
                patient_id,
                doctor_id,
                role,
                is_active
            )
            VALUES (
                'patient2',
                'p2',
                NULL,
                'patient',
                1
            )
        """)
        conn.commit()

    switch_to_patient(
        current,
        patient_id="p2",
        user_id="patient2",
    )

    detail = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )

    assert detail.status_code == 404

    listing = client.get(
        "/clinical/note-sharing/my-notes"
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 0


def test_revoke_hides_note_from_patient(notes_client):
    client, connect, current = notes_client

    note_id = create_signed_demo_note(client)

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )
    assert release.status_code == 200

    revoke = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/revoke"
    )

    assert revoke.status_code == 200
    assert revoke.json()["released"] is False

    switch_to_patient(current)

    detail = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )
    assert detail.status_code == 404

    listing = client.get(
        "/clinical/note-sharing/my-notes"
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 0

    with connect() as conn:
        events = conn.execute("""
            SELECT event_type
            FROM doctor_note_release_events
            ORDER BY created_at, rowid
        """).fetchall()

    assert [e["event_type"] for e in events] == [
        "released",
        "revoked",
    ]


def test_other_doctor_cannot_release_note(
    notes_client,
):
    client, _, current = notes_client

    note_id = create_signed_demo_note(client)

    switch_to_second_doctor(current)

    response = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    assert response.status_code == 403


def test_patient_notes_require_login(notes_client):
    client, _, _ = notes_client

    client.cookies.clear()

    response = client.get(
        "/clinical/note-sharing/my-notes"
    )

    assert response.status_code == 401


# ============================================================
# NEW AUDIT TESTS 26–35
# ============================================================

def test_clinical_audit_table_created_in_test_database(
    notes_client,
):
    _, connect, _ = notes_client

    with connect() as conn:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(clinical_audit_events)"
            ).fetchall()
        }

    assert {
        "audit_id",
        "actor_user_id",
        "actor_role",
        "patient_id",
        "note_id",
        "appointment_id",
        "event_type",
        "outcome",
        "occurred_at",
    } <= columns


def test_audit_records_note_creation_with_correct_references(
    notes_client,
):
    client, connect, _ = notes_client

    response = create_note(client)

    assert response.status_code == 201

    note_id = response.json()["note_id"]

    events = audit_events(connect)

    assert len(events) == 1

    event = events[0]

    assert event["event_type"] == "note_created"
    assert event["actor_user_id"] == "doc1"
    assert event["actor_role"] == "doctor"
    assert event["patient_id"] == "p1"
    assert event["note_id"] == note_id
    assert event["appointment_id"] == "a1"
    assert event["outcome"] == "success"

    assert event["audit_id"]
    assert event["occurred_at"]

    # The audit entry must contain metadata only.
    assert "Fictional patient reports fatigue." not in str(event)
    assert "Demo assessment." not in str(event)


def test_audit_records_note_edit(notes_client):
    client, connect, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.patch(
        f"/doctor/clinical-notes/{note_id}",
        json={
            "observations": "Updated fictional note.",
        },
    )

    assert response.status_code == 200

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "note_edited",
    ]

    assert events[-1]["note_id"] == note_id
    assert events[-1]["actor_user_id"] == "doc1"


def test_audit_records_note_signing(notes_client):
    client, connect, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/sign"
    )

    assert response.status_code == 200

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "note_signed",
    ]

    assert events[-1]["note_id"] == note_id
    assert events[-1]["appointment_id"] == "a1"


def test_audit_records_signed_note_addendum(
    notes_client,
):
    client, connect, _ = notes_client

    note_id = create_signed_demo_note(client)

    response = client.post(
        f"/doctor/clinical-notes/{note_id}/addenda",
        json={
            "content": "Fictional signed-note correction.",
        },
    )

    assert response.status_code == 201

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "note_signed",
        "note_addendum_added",
    ]

    assert events[-1]["note_id"] == note_id

    assert "Fictional signed-note correction." not in str(
        events[-1]
    )


def test_audit_records_authorized_note_view(
    notes_client,
):
    client, connect, _ = notes_client

    note_id = create_note(client).json()["note_id"]

    response = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )

    assert response.status_code == 200

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "doctor_note_viewed",
    ]

    assert events[-1]["note_id"] == note_id
    assert events[-1]["patient_id"] == "p1"


def test_audit_records_authorized_patient_note_list(
    notes_client,
):
    client, connect, _ = notes_client

    response = client.get(
        "/doctor/clinical-notes/patient/p1"
    )

    assert response.status_code == 200

    events = audit_events(connect)

    assert len(events) == 1
    assert events[0]["event_type"] == "doctor_notes_listed"
    assert events[0]["patient_id"] == "p1"
    assert events[0]["actor_user_id"] == "doc1"
    assert events[0]["note_id"] is None


def test_audit_denied_actions_do_not_log_success(
    notes_client,
):
    client, connect, current = notes_client

    note_id = create_note(client).json()["note_id"]

    switch_to_second_doctor(current)

    view = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )
    assert view.status_code == 404

    edit = client.patch(
        f"/doctor/clinical-notes/{note_id}",
        json={
            "observations": "Unauthorized change",
        },
    )
    assert edit.status_code == 404

    doctor2_events = audit_events(
        connect,
        actor_user_id="doc2",
    )

    assert doctor2_events == []

    assert [
        event["event_type"]
        for event in audit_events(connect)
    ] == ["note_created"]


def test_audit_rejected_duplicate_does_not_create_success_log(
    notes_client,
):
    client, connect, _ = notes_client

    first = create_note(client)
    second = create_note(client)

    assert first.status_code == 201
    assert second.status_code == 409

    events = audit_events(connect)

    assert [
        event["event_type"]
        for event in events
    ] == ["note_created"]


def test_audit_other_authorized_doctor_view_is_attributed(
    notes_client,
):
    client, connect, current = notes_client

    note_id = create_signed_demo_note(client)

    switch_to_second_doctor(current)

    response = client.get(
        f"/doctor/clinical-notes/{note_id}"
    )

    assert response.status_code == 200

    doctor2_events = audit_events(
        connect,
        actor_user_id="doc2",
    )

    assert len(doctor2_events) == 1
    assert doctor2_events[0]["event_type"] == (
        "doctor_note_viewed"
    )
    assert doctor2_events[0]["note_id"] == note_id
    assert doctor2_events[0]["patient_id"] == "p1"
    assert doctor2_events[0]["outcome"] == "success"

# ============================================================
# LESSON 77 — STEP 9
# CLINICAL NOTE SHARING AUDIT TESTS
# ============================================================


# TEST 36 — Doctor releasing note creates audit record
def test_audit_records_note_release(notes_client):
    client, connect, _ = notes_client

    note_id = create_signed_demo_note(client)

    response = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    assert response.status_code == 200
    assert response.json()["released"] is True

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "note_signed",
        "note_released",
    ]

    release_event = events[-1]

    assert release_event["actor_user_id"] == "doc1"
    assert release_event["actor_role"] == "doctor"
    assert release_event["patient_id"] == "p1"
    assert release_event["note_id"] == note_id
    assert release_event["appointment_id"] == "a1"
    assert release_event["outcome"] == "success"


# TEST 37 — Doctor revoking note creates audit record
def test_audit_records_note_revocation(notes_client):
    client, connect, _ = notes_client

    note_id = create_signed_demo_note(client)

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )
    assert release.status_code == 200

    revoke = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/revoke"
    )

    assert revoke.status_code == 200
    assert revoke.json()["released"] is False

    events = audit_events(connect)

    assert [e["event_type"] for e in events] == [
        "note_created",
        "note_signed",
        "note_released",
        "note_revoked",
    ]

    revoke_event = events[-1]

    assert revoke_event["actor_user_id"] == "doc1"
    assert revoke_event["patient_id"] == "p1"
    assert revoke_event["note_id"] == note_id
    assert revoke_event["outcome"] == "success"


# TEST 38 — Patient listing notes creates audit record
def test_audit_records_patient_notes_list(
    notes_client,
):
    client, connect, current = notes_client

    note_id = create_signed_demo_note(client)

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )
    assert release.status_code == 200

    switch_to_patient(current)

    response = client.get(
        "/clinical/note-sharing/my-notes"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1

    events = audit_events(
        connect,
        actor_user_id="patient1",
    )

    assert len(events) == 1

    event = events[0]

    assert event["event_type"] == "patient_notes_listed"
    assert event["actor_role"] == "patient"
    assert event["patient_id"] == "p1"
    assert event["note_id"] is None
    assert event["outcome"] == "success"


# TEST 39 — Patient viewing released note creates audit
def test_audit_records_patient_note_view(
    notes_client,
):
    client, connect, current = notes_client

    note_id = create_signed_demo_note(client)

    release = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )
    assert release.status_code == 200

    switch_to_patient(current)

    response = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )

    assert response.status_code == 200

    events = audit_events(
        connect,
        actor_user_id="patient1",
    )

    assert len(events) == 1

    event = events[0]

    assert event["event_type"] == "patient_note_viewed"
    assert event["actor_role"] == "patient"
    assert event["patient_id"] == "p1"
    assert event["note_id"] == note_id
    assert event["appointment_id"] == "a1"
    assert event["outcome"] == "success"

    # No clinical-note contents should enter audit logs.
    assert "Fictional patient reports fatigue." not in str(
        event
    )


# TEST 40 — Private note cannot create successful view audit
def test_audit_private_note_view_does_not_log_success(
    notes_client,
):
    client, connect, current = notes_client

    # The note is signed but has not been released.
    note_id = create_signed_demo_note(client)

    switch_to_patient(current)

    response = client.get(
        f"/clinical/note-sharing/my-notes/{note_id}"
    )

    assert response.status_code == 404

    patient_events = audit_events(
        connect,
        actor_user_id="patient1",
    )

    assert patient_events == []


# TEST 41 — Duplicate release cannot create success audit
def test_audit_duplicate_release_does_not_log_success(
    notes_client,
):
    client, connect, _ = notes_client

    note_id = create_signed_demo_note(client)

    first = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    second = client.post(
        f"/clinical/note-sharing/doctor/{note_id}/release"
    )

    assert first.status_code == 200
    assert second.status_code == 409

    events = audit_events(connect)

    release_events = [
        event
        for event in events
        if event["event_type"] == "note_released"
    ]

    assert len(release_events) == 1
    assert release_events[0]["note_id"] == note_id
