
import hashlib
import io
import sqlite3

import pytest

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app
from app.routers import (
    clinical_patients,
    doctor_documents,
    medical_documents,
)

from scripts.create_care_team import create_care_team_tables
from scripts.create_patient_documents import create_document_tables
from scripts.create_clinical_audit import (
    create_clinical_audit_tables,
)


# ============================================================
# TEST DATA
# ============================================================

def make_pdf():
    buffer = io.BytesIO()

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)

    return buffer.getvalue()


# ============================================================
# TEST DATABASE AND AUTHENTICATION FIXTURE
# ============================================================

@pytest.fixture
def doctor_client(tmp_path, monkeypatch):
    db_path = tmp_path / "doctor_documents.db"

    private_dir = tmp_path / "private_uploads"
    private_dir.mkdir()

    def connect():
        conn = sqlite3.connect(db_path)
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
                is_active INTEGER NOT NULL
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

        # Existing tables.
        create_care_team_tables(conn)
        create_document_tables(conn)

        # NEW: create audit tables in the isolated
        # test database before using document endpoints.
        create_clinical_audit_tables(conn)

        conn.executemany(
            "INSERT INTO patients VALUES (?, ?)",
            [
                ("patient-a", "Alex Morgan"),
                ("patient-b", "Jamie Lee"),
            ],
        )

        conn.executemany(
            "INSERT INTO doctors VALUES (?, ?)",
            [
                ("doctor-a", 1),
                ("doctor-b", 1),
            ],
        )

        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            [
                ("admin-a", None, None, "admin", 1),
                (
                    "doctor-user-a",
                    None,
                    "doctor-a",
                    "doctor",
                    1,
                ),
                (
                    "doctor-user-b",
                    None,
                    "doctor-b",
                    "doctor",
                    1,
                ),
                (
                    "nurse-user",
                    None,
                    None,
                    "nurse",
                    1,
                ),
                (
                    "patient-user-a",
                    "patient-a",
                    None,
                    "patient",
                    1,
                ),
                (
                    "patient-user-b",
                    "patient-b",
                    None,
                    "patient",
                    1,
                ),
            ],
        )

        conn.executemany("""
            INSERT INTO care_team_assignments (
                assignment_id,
                patient_id,
                staff_user_id,
                assigned_by_user_id
            )
            VALUES (?, ?, ?, 'admin-a')
        """, [
            (
                "assignment-a",
                "patient-a",
                "doctor-user-a",
            ),
            (
                "assignment-b",
                "patient-b",
                "doctor-user-b",
            ),
        ])

        pdf_a = make_pdf()
        pdf_b = make_pdf()

        key_a = "a" * 32 + ".pdf"
        key_b = "b" * 32 + ".pdf"

        (private_dir / key_a).write_bytes(pdf_a)
        (private_dir / key_b).write_bytes(pdf_b)

        conn.executemany("""
            INSERT INTO patient_documents (
                document_id,
                patient_id,
                uploaded_by_user_id,
                original_filename,
                media_type,
                size_bytes,
                sha256,
                storage_key,
                uploaded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                "doc-a",
                "patient-a",
                "patient-user-a",
                "blood-report.pdf",
                "application/pdf",
                len(pdf_a),
                hashlib.sha256(pdf_a).hexdigest(),
                key_a,
                "2026-11-07T12:00:00+00:00",
            ),
            (
                "doc-b",
                "patient-b",
                "patient-user-b",
                "other-report.pdf",
                "application/pdf",
                len(pdf_b),
                hashlib.sha256(pdf_b).hexdigest(),
                key_b,
                "2026-11-07T13:00:00+00:00",
            ),
        ])

        conn.commit()

    # Default authenticated doctor.
    current = {
        "user": {
            "user_id": "doctor-user-a",
            "doctor_id": "doctor-a",
            "role": "doctor",
        }
    }

    # Route database operations to the test database.
    monkeypatch.setattr(
        doctor_documents,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        clinical_patients,
        "get_db",
        connect,
    )

    # Simulated session authentication.
    monkeypatch.setattr(
        clinical_patients,
        "get_current_user",
        lambda token: current["user"],
    )

    # Keep all test uploads inside tmp_path.
    monkeypatch.setattr(
        medical_documents,
        "PRIVATE_DIR",
        private_dir,
    )

    with TestClient(app) as client:
        client.cookies.set(
            "hospital_session",
            "fictional-test-session",
        )

        yield client, connect, current, pdf_a


# ============================================================
# TEST HELPERS
# ============================================================

def list_documents(
    client,
    patient_id="patient-a",
):
    return client.get(
        f"/doctor/patients/{patient_id}/medical-documents"
    )


def download_document(
    client,
    patient_id="patient-a",
    document_id="doc-a",
):
    return client.get(
        f"/doctor/patients/{patient_id}"
        f"/medical-documents/{document_id}/download"
    )


def get_audit_events(
    connect,
    actor_user_id=None,
):
    """
    Read audit entries from the temporary test database.
    """

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
            """, (
                actor_user_id,
            )).fetchall()

    return [dict(row) for row in rows]


# ============================================================
# EXISTING DOCUMENT TESTS
# ============================================================

def test_assigned_doctor_can_list_documents(
    doctor_client,
):
    client, _, _, _ = doctor_client

    response = list_documents(client)

    assert response.status_code == 200
    assert response.json()["total"] == 1

    document = response.json()["documents"][0]

    assert document["filename"] == "blood-report.pdf"
    assert "storage_key" not in document
    assert "sha256" not in document


def test_assigned_doctor_can_download_document(
    doctor_client,
):
    client, _, _, expected_pdf = doctor_client

    response = download_document(client)

    assert response.status_code == 200
    assert response.content == expected_pdf

    assert response.headers["content-type"] == (
        "application/pdf"
    )

    assert response.headers["cache-control"] == (
        "private, no-store"
    )


def test_unassigned_doctor_cannot_list(
    doctor_client,
):
    client, _, current, _ = doctor_client

    current["user"] = {
        "user_id": "doctor-user-b",
        "doctor_id": "doctor-b",
        "role": "doctor",
    }

    response = list_documents(client)

    assert response.status_code == 404


def test_unassigned_doctor_cannot_download(
    doctor_client,
):
    client, _, current, _ = doctor_client

    current["user"] = {
        "user_id": "doctor-user-b",
        "doctor_id": "doctor-b",
        "role": "doctor",
    }

    response = download_document(client)

    assert response.status_code == 404


def test_cannot_download_another_patients_document(
    doctor_client,
):
    client, _, _, _ = doctor_client

    response = download_document(
        client,
        "patient-a",
        "doc-b",
    )

    assert response.status_code == 404


def test_revocation_removes_document_access(
    doctor_client,
):
    client, connect, _, _ = doctor_client

    with connect() as conn:
        conn.execute("""
            UPDATE care_team_assignments
            SET revoked_at = '2026-11-07T18:00:00+00:00'
            WHERE assignment_id = 'assignment-a'
        """)
        conn.commit()

    assert list_documents(client).status_code == 404

    assert download_document(client).status_code == 404


@pytest.mark.parametrize(
    "role",
    ["nurse", "patient"],
)
def test_non_doctor_cannot_access_documents(
    doctor_client,
    role,
):
    client, _, current, _ = doctor_client

    current["user"] = {
        "user_id": (
            "nurse-user"
            if role == "nurse"
            else "patient-user-a"
        ),
        "role": role,
        "patient_id": (
            "patient-a"
            if role == "patient"
            else None
        ),
    }

    response = list_documents(client)

    assert response.status_code == 403


def test_missing_session_is_rejected(
    doctor_client,
):
    client, _, _, _ = doctor_client

    client.cookies.clear()

    response = list_documents(client)

    assert response.status_code == 401


def test_unknown_document_returns_404(
    doctor_client,
):
    client, _, _, _ = doctor_client

    response = download_document(
        client,
        document_id="does-not-exist",
    )

    assert response.status_code == 404


# ============================================================
# LESSON 77 — DOCUMENT AUDIT TESTS
# ============================================================

# TEST 1 — Successful download records an audit event.

def test_download_creates_clinical_audit_event(
    doctor_client,
):
    client, connect, _, expected_pdf = doctor_client

    response = download_document(client)

    assert response.status_code == 200
    assert response.content == expected_pdf

    events = get_audit_events(connect)

    assert len(events) == 1

    event = events[0]

    assert event["audit_id"]
    assert event["occurred_at"]

    assert event["actor_user_id"] == (
        "doctor-user-a"
    )

    assert event["actor_role"] == "doctor"

    assert event["patient_id"] == "patient-a"

    assert event["event_type"] == (
        "medical_document_downloaded"
    )

    assert event["outcome"] == "success"

    # The current audit schema does not include
    # a document_id column.
    assert event["note_id"] is None
    assert event["appointment_id"] is None

    # Do not store private filenames or storage keys.
    assert "blood-report.pdf" not in str(event)
    assert ("a" * 32 + ".pdf") not in str(event)


# TEST 2 — Unauthorized doctor does not create success event.

def test_unauthorized_download_does_not_create_success_audit(
    doctor_client,
):
    client, connect, current, _ = doctor_client

    current["user"] = {
        "user_id": "doctor-user-b",
        "doctor_id": "doctor-b",
        "role": "doctor",
    }

    response = download_document(client)

    assert response.status_code == 404

    events = get_audit_events(connect)

    assert events == []


# TEST 3 — Unknown document does not create success event.

def test_missing_document_does_not_create_success_audit(
    doctor_client,
):
    client, connect, _, _ = doctor_client

    response = download_document(
        client,
        document_id="does-not-exist",
    )

    assert response.status_code == 404

    events = get_audit_events(connect)

    assert events == []


# TEST 4 — Missing physical file does not create success event.

def test_missing_physical_file_does_not_create_success_audit(
    doctor_client,
):
    client, connect, _, _ = doctor_client

    storage_key = "a" * 32 + ".pdf"

    file_path = (
        medical_documents.PRIVATE_DIR / storage_key
    )

    assert file_path.is_file()

    # Remove only the fictional file in this test's
    # temporary upload directory.
    file_path.unlink()

    response = download_document(client)

    assert response.status_code == 404

    events = get_audit_events(connect)

    assert events == []
