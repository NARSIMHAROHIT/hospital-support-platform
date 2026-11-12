
import re

from contextlib import closing

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse

from app.core.database import get_db
from app.core.care_access import authorize_record_action
from app.core.clinical_audit import record_clinical_audit

from app.routers.clinical_patients import require_clinical_staff
from app.routers import medical_documents


router = APIRouter(
    prefix="/doctor/patients",
    tags=["Doctor Medical Documents"],
)


# ============================================================
# DOCTOR AUTHORIZATION
# ============================================================

def require_doctor_documents(
    user: dict = Depends(require_clinical_staff),
):
    """
    Restrict these document endpoints to doctors.

    Nurses and other clinical roles cannot access
    the doctor-only document endpoints.
    """

    if user.get("role") != "doctor":
        raise HTTPException(
            status_code=403,
            detail="Doctor access required",
        )

    return user


# ============================================================
# LIST PATIENT MEDICAL DOCUMENTS
# ============================================================

@router.get("/{patient_id}/medical-documents")
def list_patient_documents(
    patient_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_doctor_documents),
):
    with closing(get_db()) as conn:

        # Check authorization before retrieving records.
        authorize_record_action(
            conn,
            user,
            patient_id,
            "records:read",
        )

        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM patient_documents
            WHERE patient_id = ?
        """, (patient_id,)).fetchone()["total"]

        documents = conn.execute("""
            SELECT
                document_id,
                original_filename AS filename,
                media_type,
                size_bytes,
                uploaded_at
            FROM patient_documents
            WHERE patient_id = ?
            ORDER BY
                uploaded_at DESC,
                document_id DESC
            LIMIT ? OFFSET ?
        """, (
            patient_id,
            limit,
            offset,
        )).fetchall()

    return {
        "patient_id": patient_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "documents": [
            dict(row)
            for row in documents
        ],
    }


# ============================================================
# DOWNLOAD PATIENT MEDICAL DOCUMENT
# WITH CLINICAL AUDIT LOGGING
# ============================================================

@router.get(
    "/{patient_id}/medical-documents/{document_id}/download"
)
def download_patient_document(
    patient_id: str,
    document_id: str,
    user: dict = Depends(require_doctor_documents),
):
    """
    Allow an authorized doctor to download a patient's
    uploaded medical document.

    Security checks:
    - Doctor role required.
    - Active patient access required.
    - Document must belong to the requested patient.
    - Storage key must follow the expected format.
    - File must exist inside the private directory.
    - Symbolic links are rejected.

    Audit:
    - Records a successful, authorized download request.
    - Does not store medical document contents.
    - Does not store the filename or storage path.
    - Commits the audit before returning FileResponse.

    Note:
    The audit confirms that a valid file response was
    initiated. It cannot guarantee that the client
    received the complete file over the network.
    """

    with closing(get_db()) as conn:

        # ----------------------------------------------------
        # 1. AUTHORIZE DOCTOR ACCESS
        # ----------------------------------------------------

        authorize_record_action(
            conn,
            user,
            patient_id,
            "records:read",
        )

        # ----------------------------------------------------
        # 2. RETRIEVE DOCUMENT METADATA
        # ----------------------------------------------------

        document = conn.execute("""
            SELECT
                original_filename,
                media_type,
                storage_key
            FROM patient_documents
            WHERE document_id = ?
              AND patient_id = ?
            LIMIT 1
        """, (
            document_id,
            patient_id,
        )).fetchone()

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found",
            )

        # ----------------------------------------------------
        # 3. VALIDATE PRIVATE STORAGE KEY
        # ----------------------------------------------------

        storage_key = document["storage_key"]

        # Accept only generated storage filenames:
        #
        # 32 lowercase hexadecimal characters followed
        # by an allowed extension.
        #
        # Examples:
        # abcdef0123456789abcdef0123456789.pdf
        # abcdef0123456789abcdef0123456789.png

        if (
            not isinstance(storage_key, str)
            or not re.fullmatch(
                r"[0-9a-f]{32}\.(?:pdf|png|jpg|jpeg)",
                storage_key,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Document not found",
            )

        # ----------------------------------------------------
        # 4. RESOLVE PRIVATE STORAGE PATH
        # ----------------------------------------------------

        storage_dir = (
            medical_documents.PRIVATE_DIR.resolve()
        )

        file_path = storage_dir / storage_key

        # ----------------------------------------------------
        # 5. VERIFY FILE SAFETY
        # ----------------------------------------------------

        if (
            file_path.is_symlink()
            or not file_path.is_file()
            or file_path.resolve().parent != storage_dir
        ):
            raise HTTPException(
                status_code=404,
                detail="Document file not found",
            )

        # ----------------------------------------------------
        # 6. RECORD CLINICAL AUDIT EVENT
        # ----------------------------------------------------

        # Log the authorized download request only after
        # all access and file validation checks succeed.
        #
        # Existing audit schema stores actor and patient
        # metadata but does not yet include document_id.
        # Do not misuse note_id for a document reference.

        record_clinical_audit(
            conn,
            actor_user_id=user["user_id"],
            actor_role=user["role"],
            event_type="medical_document_downloaded",
            patient_id=patient_id,
            outcome="success",
        )

        # Ensure the audit event is stored before
        # initiating the file response.
        conn.commit()

        filename = document["original_filename"]
        media_type = document["media_type"]

    # --------------------------------------------------------
    # 7. RETURN DOCUMENT TO AUTHORIZED DOCTOR
    # --------------------------------------------------------

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
