
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.main import app
from app.routers import medical_documents
from scripts.create_patient_documents import (
    create_document_tables,
)


def make_pdf():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(output)
    return output.getvalue()


def make_image(image_format):
    output = io.BytesIO()
    image = Image.new("RGB", (20, 20), "white")
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def document_client(tmp_path, monkeypatch):
    db_path = tmp_path / "documents.db"
    storage_dir = tmp_path / "private_uploads"

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
            [("patient-a",), ("patient-b",)],
        )

        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?)",
            [
                ("user-a", "patient-a", "patient", 1),
                ("user-b", "patient-b", "patient", 1),
            ],
        )

        create_document_tables(conn)
        conn.commit()

    current = {
        "user": {
            "user_id": "user-a",
            "patient_id": "patient-a",
            "role": "patient",
        }
    }

    monkeypatch.setattr(
        medical_documents,
        "get_db",
        connect,
    )

    monkeypatch.setattr(
        medical_documents,
        "PRIVATE_DIR",
        storage_dir,
    )

    monkeypatch.setattr(
        medical_documents,
        "get_current_user",
        lambda token: current["user"],
    )

    app.dependency_overrides[
        medical_documents.check_request_origin
    ] = lambda: None

    try:
        with TestClient(app) as client:
            client.cookies.set(
                "hospital_session",
                "test-session",
            )

            yield client, current, connect, storage_dir

    finally:
        app.dependency_overrides.pop(
            medical_documents.check_request_origin,
            None,
        )


def upload(client, name, content, content_type):
    return client.post(
        "/my/medical-documents",
        files={
            "file": (
                name,
                content,
                content_type,
            )
        },
    )


def test_pdf_upload_and_listing(document_client):
    client, _, connect, storage_dir = document_client
    pdf = make_pdf()

    response = upload(
        client,
        "blood-report.pdf",
        pdf,
        "application/pdf",
    )

    assert response.status_code == 201

    result = response.json()

    assert result["filename"] == "blood-report.pdf"
    assert result["size_bytes"] == len(pdf)
    assert "storage_key" not in result

    listed = client.get("/my/medical-documents")

    assert listed.status_code == 200
    assert len(listed.json()["documents"]) == 1

    with connect() as conn:
        row = conn.execute("""
            SELECT storage_key
            FROM patient_documents
        """).fetchone()

    assert row["storage_key"] != "blood-report.pdf"
    assert (storage_dir / row["storage_key"]).exists()


def test_pdf_download(document_client):
    client, _, _, _ = document_client
    pdf = make_pdf()

    uploaded = upload(
        client,
        "report.pdf",
        pdf,
        "application/pdf",
    )

    document_id = uploaded.json()["document_id"]

    response = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"] == (
        "application/pdf"
    )
    assert response.headers["cache-control"] == (
        "private, no-store"
    )


def test_png_upload(document_client):
    client, _, _, _ = document_client

    response = upload(
        client,
        "scan.png",
        make_image("PNG"),
        "image/png",
    )

    assert response.status_code == 201
    assert response.json()["media_type"] == "image/png"


def test_jpeg_upload(document_client):
    client, _, _, _ = document_client

    response = upload(
        client,
        "scan.jpg",
        make_image("JPEG"),
        "image/jpeg",
    )

    assert response.status_code == 201
    assert response.json()["media_type"] == "image/jpeg"


def test_mismatched_file_format_rejected(
    document_client,
):
    client, _, _, storage_dir = document_client

    response = upload(
        client,
        "fake.png",
        make_pdf(),
        "image/png",
    )

    assert response.status_code == 415
    assert list(storage_dir.glob("*")) == []


def test_unsupported_extension_rejected(
    document_client,
):
    client, _, _, _ = document_client

    response = upload(
        client,
        "program.exe",
        b"not a medical document",
        "application/octet-stream",
    )

    assert response.status_code == 415


def test_empty_file_rejected(document_client):
    client, _, _, _ = document_client

    response = upload(
        client,
        "empty.pdf",
        b"",
        "application/pdf",
    )

    assert response.status_code == 400


def test_oversized_file_rejected(
    document_client,
    monkeypatch,
):
    client, _, _, _ = document_client

    monkeypatch.setattr(
        medical_documents,
        "MAX_UPLOAD_BYTES",
        20,
    )

    response = upload(
        client,
        "large.pdf",
        b"x" * 21,
        "application/pdf",
    )

    assert response.status_code == 413


def test_patient_cannot_access_another_patients_files(
    document_client,
):
    client, current, _, _ = document_client

    uploaded = upload(
        client,
        "private.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert uploaded.status_code == 201

    document_id = uploaded.json()["document_id"]

    current["user"] = {
        "user_id": "user-b",
        "patient_id": "patient-b",
        "role": "patient",
    }

    listing = client.get("/my/medical-documents")
    assert listing.status_code == 200
    assert listing.json()["documents"] == []

    download = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    assert download.status_code == 404


def test_doctor_cannot_use_patient_upload_endpoint(
    document_client,
):
    client, current, _, _ = document_client

    current["user"] = {
        "user_id": "doctor-demo",
        "role": "doctor",
        "doctor_id": "doctor-demo",
    }

    response = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert response.status_code == 403


def test_missing_session_rejected(document_client):
    client, _, _, _ = document_client

    client.cookies.clear()

    response = client.get("/my/medical-documents")

    assert response.status_code == 401



# ============================================================
# LESSON 78 — PATIENT DOCUMENT SECURITY TESTS
# ============================================================


# TEST 12 — An unknown document cannot be downloaded.

def test_unknown_document_download_returns_404(
    document_client,
):
    client, _, _, _ = document_client

    response = client.get(
        "/my/medical-documents/nonexistent-document/download"
    )

    assert response.status_code == 404


# TEST 13 — An inactive patient cannot access documents.

def test_inactive_patient_cannot_access_documents(
    document_client,
):
    client, _, connect, _ = document_client

    pdf = make_pdf()

    uploaded = upload(
        client,
        "report.pdf",
        pdf,
        "application/pdf",
    )

    assert uploaded.status_code == 201
    document_id = uploaded.json()["document_id"]

    with connect() as conn:
        conn.execute("""
            UPDATE users
            SET is_active = 0
            WHERE user_id = 'user-a'
        """)
        conn.commit()

    listing = client.get("/my/medical-documents")

    download = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    new_upload = upload(
        client,
        "another.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert listing.status_code in (401, 403)
    assert download.status_code in (401, 403)
    assert new_upload.status_code in (401, 403)


# TEST 14 — Session identity must match database ownership.

def test_patient_session_identity_mismatch_rejected(
    document_client,
):
    client, current, _, _ = document_client

    # Session claims patient-b, but user-a belongs
    # to patient-a in the database.
    current["user"] = {
        "user_id": "user-a",
        "patient_id": "patient-b",
        "role": "patient",
    }

    listing = client.get("/my/medical-documents")

    new_upload = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert listing.status_code in (401, 403)
    assert new_upload.status_code in (401, 403)


# TEST 15 — Missing physical files must not be served.

def test_missing_physical_document_returns_404(
    document_client,
):
    client, _, connect, storage_dir = document_client

    uploaded = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert uploaded.status_code == 201

    document_id = uploaded.json()["document_id"]

    with connect() as conn:
        document = conn.execute("""
            SELECT storage_key
            FROM patient_documents
            WHERE document_id = ?
        """, (document_id,)).fetchone()

    file_path = storage_dir / document["storage_key"]

    assert file_path.is_file()

    file_path.unlink()

    response = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    assert response.status_code == 404


# TEST 16 — Symbolic links must not expose external files.

def test_symlink_document_download_rejected(
    document_client,
):
    client, _, connect, storage_dir = document_client

    uploaded = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert uploaded.status_code == 201

    document_id = uploaded.json()["document_id"]

    with connect() as conn:
        document = conn.execute("""
            SELECT storage_key
            FROM patient_documents
            WHERE document_id = ?
        """, (document_id,)).fetchone()

    file_path = storage_dir / document["storage_key"]

    # Create a fictional file outside private storage.
    outside_file = storage_dir.parent / "external.pdf"
    outside_file.write_bytes(make_pdf())

    file_path.unlink()

    # Replace the stored file with a symlink.
    file_path.symlink_to(outside_file)

    response = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    assert response.status_code == 404


# TEST 17 — Unsafe storage paths must be rejected.

def test_storage_path_traversal_rejected(
    document_client,
):
    client, _, connect, storage_dir = document_client

    uploaded = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert uploaded.status_code == 201

    document_id = uploaded.json()["document_id"]

    # Create a fictional external file to test
    # whether unsafe stored paths can escape the
    # private upload directory.
    outside_file = storage_dir.parent / "outside.pdf"
    outside_file.write_bytes(make_pdf())

    with connect() as conn:
        conn.execute("""
            UPDATE patient_documents
            SET storage_key = '../outside.pdf'
            WHERE document_id = ?
        """, (document_id,))
        conn.commit()

    response = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    assert response.status_code == 404


# TEST 18 — Patients can upload only to their own accounts.

def test_each_patient_upload_is_isolated(
    document_client,
):
    client, current, connect, _ = document_client

    upload_a = upload(
        client,
        "patient-a.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert upload_a.status_code == 201

    doc_a = upload_a.json()["document_id"]

    # Switch to patient B.
    current["user"] = {
        "user_id": "user-b",
        "patient_id": "patient-b",
        "role": "patient",
    }

    upload_b = upload(
        client,
        "patient-b.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert upload_b.status_code == 201

    doc_b = upload_b.json()["document_id"]

    listing_b = client.get("/my/medical-documents")

    assert listing_b.status_code == 200
    assert len(listing_b.json()["documents"]) == 1

    assert listing_b.json()["documents"][0][
        "document_id"
    ] == doc_b

    # Patient B cannot access patient A's file.
    forbidden = client.get(
        f"/my/medical-documents/{doc_a}/download"
    )

    assert forbidden.status_code == 404

    # Confirm database ownership.
    with connect() as conn:
        rows = conn.execute("""
            SELECT document_id, patient_id
            FROM patient_documents
            ORDER BY document_id
        """).fetchall()

    ownership = {
        row["document_id"]: row["patient_id"]
        for row in rows
    }

    assert ownership[doc_a] == "patient-a"
    assert ownership[doc_b] == "patient-b"


# TEST 19 — Logout blocks document download and upload.

def test_missing_session_blocks_download_and_upload(
    document_client,
):
    client, _, _, _ = document_client

    uploaded = upload(
        client,
        "report.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert uploaded.status_code == 201

    document_id = uploaded.json()["document_id"]

    # Simulate logout.
    client.cookies.clear()

    download = client.get(
        f"/my/medical-documents/{document_id}/download"
    )

    new_upload = upload(
        client,
        "another.pdf",
        make_pdf(),
        "application/pdf",
    )

    assert download.status_code == 401
    assert new_upload.status_code == 401
