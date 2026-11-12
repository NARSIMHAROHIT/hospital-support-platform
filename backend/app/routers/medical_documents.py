
import hashlib
import os
import re

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse

from PIL import Image
from pypdf import PdfReader

from app.core.database import get_db
from app.core.security import get_current_user
from app.routers.appointments import check_request_origin


router = APIRouter(
    prefix="/my/medical-documents",
    tags=["Patient Medical Documents"],
)


# ============================================================
# CONFIGURATION
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[2]

PRIVATE_DIR = Path(
    os.getenv(
        "MEDICAL_FILES_DIR",
        str(BACKEND_DIR / "private_uploads"),
    )
).resolve()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000

ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Uploaded files use a server-generated UUID storage key.
STORAGE_KEY_PATTERN = re.compile(
    r"[0-9a-f]{32}\.(?:pdf|png|jpg|jpeg)"
)


# ============================================================
# PATIENT AUTHENTICATION AND AUTHORIZATION
# ============================================================

def require_patient_session(
    hospital_session: str | None = Cookie(default=None),
):
    """
    Validate a patient session against the database.

    Security checks:
    1. Session cookie must exist.
    2. Session must resolve to a valid user.
    3. User must have the patient role.
    4. User account must exist and be active.
    5. Session patient_id must match the database.
    """

    # --------------------------------------------------------
    # 1. CHECK SESSION COOKIE
    # --------------------------------------------------------

    if not hospital_session:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    # --------------------------------------------------------
    # 2. VALIDATE SESSION
    # --------------------------------------------------------

    authenticated_user = get_current_user(
        hospital_session
    )

    if not authenticated_user:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    user = dict(authenticated_user)

    # --------------------------------------------------------
    # 3. REQUIRE PATIENT ROLE
    # --------------------------------------------------------

    if user.get("role") != "patient":
        raise HTTPException(
            status_code=403,
            detail="Patient access required",
        )

    user_id = user.get("user_id")
    session_patient_id = user.get("patient_id")

    if not user_id or not session_patient_id:
        raise HTTPException(
            status_code=403,
            detail="Patient account is not linked",
        )

    # --------------------------------------------------------
    # 4. VERIFY ACCOUNT AGAINST DATABASE
    # --------------------------------------------------------

    with closing(get_db()) as conn:
        account = conn.execute("""
            SELECT
                patient_id,
                is_active
            FROM users
            WHERE user_id = ?
              AND role = 'patient'
            LIMIT 1
        """, (
            user_id,
        )).fetchone()

    # Reject deleted or missing accounts.
    if account is None:
        raise HTTPException(
            status_code=403,
            detail="Active patient account required",
        )

    # Reject disabled accounts.
    if not account["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Active patient account required",
        )

    database_patient_id = account["patient_id"]

    if not database_patient_id:
        raise HTTPException(
            status_code=403,
            detail="Patient account is not linked",
        )

    # --------------------------------------------------------
    # 5. PREVENT SESSION IDENTITY MISMATCH
    # --------------------------------------------------------

    if database_patient_id != session_patient_id:
        raise HTTPException(
            status_code=403,
            detail="Patient session identity mismatch",
        )

    return user


# ============================================================
# FILENAME SANITIZATION
# ============================================================

def clean_filename(filename):
    """
    Remove directory components and nonprintable
    characters from the original filename.
    """

    name = (filename or "").replace("\\", "/")

    name = name.rsplit("/", 1)[-1]

    name = "".join(
        character
        for character in name
        if character.isprintable()
    ).strip()

    return name[:160]


# ============================================================
# UPLOADED FILE VALIDATION
# ============================================================

def validate_file(file_path, extension):
    """
    Validate basic PDF and image formats.

    This does not replace antivirus scanning.
    """

    if extension == ".pdf":

        try:
            with file_path.open("rb") as stream:

                # Verify actual PDF signature.
                if stream.read(5) != b"%PDF-":
                    raise ValueError(
                        "Invalid PDF signature"
                    )

            reader = PdfReader(str(file_path))

            if reader.is_encrypted:
                raise ValueError(
                    "Encrypted PDFs are unsupported"
                )

            if len(reader.pages) == 0:
                raise ValueError(
                    "PDF has no pages"
                )

            if len(reader.pages) > 200:
                raise ValueError(
                    "PDF has too many pages"
                )

        except Exception:
            raise HTTPException(
                status_code=415,
                detail="Invalid or unsupported PDF",
            )

    else:

        try:
            with Image.open(file_path) as image:

                expected = (
                    "PNG"
                    if extension == ".png"
                    else "JPEG"
                )

                if image.format != expected:
                    raise ValueError(
                        "Image format mismatch"
                    )

                if (
                    image.width * image.height
                    > MAX_IMAGE_PIXELS
                ):
                    raise ValueError(
                        "Image is too large"
                    )

                image.verify()

        except Exception:
            raise HTTPException(
                status_code=415,
                detail="Invalid or unsupported image",
            )


# ============================================================
# PATIENT MEDICAL DOCUMENT UPLOAD
# ============================================================

@router.post("", status_code=201)
async def upload_medical_document(
    file: UploadFile = File(...),
    user: dict = Depends(require_patient_session),
    _origin=Depends(check_request_origin),
):
    """
    Upload a patient-owned medical document.

    Authorization is performed before processing
    or saving the uploaded file.
    """

    filename = clean_filename(file.filename)

    extension = Path(filename).suffix.lower()

    # --------------------------------------------------------
    # 1. VALIDATE FILE TYPE
    # --------------------------------------------------------

    if extension not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Only PDF, PNG and JPEG files are supported"
            ),
        )

    # --------------------------------------------------------
    # 2. PREPARE PRIVATE STORAGE
    # --------------------------------------------------------

    PRIVATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    document_id = str(uuid4())

    # Use a random storage key, never a patient filename.
    storage_key = f"{uuid4().hex}{extension}"

    file_path = PRIVATE_DIR / storage_key

    size_bytes = 0

    checksum = hashlib.sha256()

    try:

        # ----------------------------------------------------
        # 3. CREATE FILE WITH RESTRICTED PERMISSIONS
        # ----------------------------------------------------

        descriptor = os.open(
            file_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )

        # ----------------------------------------------------
        # 4. STREAM UPLOAD IN CHUNKS
        # ----------------------------------------------------

        with os.fdopen(descriptor, "wb") as destination:

            while True:

                chunk = await file.read(64 * 1024)

                if not chunk:
                    break

                size_bytes += len(chunk)

                if size_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Maximum file size is 10 MB",
                    )

                checksum.update(chunk)

                destination.write(chunk)

        # ----------------------------------------------------
        # 5. REJECT EMPTY FILES
        # ----------------------------------------------------

        if size_bytes == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot upload an empty file",
            )

        # ----------------------------------------------------
        # 6. VALIDATE ACTUAL FILE CONTENT
        # ----------------------------------------------------

        validate_file(
            file_path,
            extension,
        )

        uploaded_at = datetime.now(
            timezone.utc
        ).isoformat()

        # ----------------------------------------------------
        # 7. SAVE DOCUMENT METADATA
        # ----------------------------------------------------

        with closing(get_db()) as conn:

            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            conn.execute("""
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
            """, (
                document_id,
                user["patient_id"],
                user["user_id"],
                filename,
                ALLOWED_TYPES[extension],
                size_bytes,
                checksum.hexdigest(),
                storage_key,
                uploaded_at,
            ))

            conn.commit()

        # ----------------------------------------------------
        # 8. RETURN SAFE UPLOAD RESPONSE
        # ----------------------------------------------------

        return {
            "document_id": document_id,
            "filename": filename,
            "media_type": ALLOWED_TYPES[extension],
            "size_bytes": size_bytes,
            "uploaded_at": uploaded_at,
        }

    except Exception:

        # Remove a partially written file after failure.
        file_path.unlink(missing_ok=True)

        raise

    finally:

        await file.close()


# ============================================================
# PATIENT MEDICAL DOCUMENT LISTING
# ============================================================

@router.get("")
def list_medical_documents(
    user: dict = Depends(require_patient_session),
):
    """
    Return only the authenticated patient's documents.
    """

    with closing(get_db()) as conn:

        rows = conn.execute("""
            SELECT
                document_id,
                original_filename AS filename,
                media_type,
                size_bytes,
                uploaded_at
            FROM patient_documents
            WHERE patient_id = ?
            ORDER BY uploaded_at DESC
        """, (
            user["patient_id"],
        )).fetchall()

    return {
        "documents": [
            dict(row)
            for row in rows
        ]
    }


# ============================================================
# PATIENT MEDICAL DOCUMENT DOWNLOAD
# ============================================================

@router.get("/{document_id}/download")
def download_medical_document(
    document_id: str,
    user: dict = Depends(require_patient_session),
):
    """
    Download an authorized patient's medical document.

    Security checks:
    - The patient session must be valid and active.
    - The session identity must match the database.
    - The document must belong to that patient.
    - Storage key must have the expected format.
    - Symbolic links must be rejected.
    - Files outside private storage must be rejected.
    - Missing files must return HTTP 404.
    """

    # --------------------------------------------------------
    # 1. QUERY DOCUMENT FOR AUTHENTICATED PATIENT
    # --------------------------------------------------------

    with closing(get_db()) as conn:

        row = conn.execute("""
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
            user["patient_id"],
        )).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    # --------------------------------------------------------
    # 2. VALIDATE STORAGE KEY
    # --------------------------------------------------------

    storage_key = row["storage_key"]

    if (
        not isinstance(storage_key, str)
        or STORAGE_KEY_PATTERN.fullmatch(
            storage_key
        ) is None
    ):
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    # --------------------------------------------------------
    # 3. RESOLVE PRIVATE STORAGE DIRECTORY
    # --------------------------------------------------------

    storage_dir = PRIVATE_DIR.resolve()

    file_path = storage_dir / storage_key

    # --------------------------------------------------------
    # 4. REJECT SYMBOLIC LINKS
    # --------------------------------------------------------

    if file_path.is_symlink():
        raise HTTPException(
            status_code=404,
            detail="Document file not found",
        )

    # --------------------------------------------------------
    # 5. REJECT MISSING OR NON-FILE PATHS
    # --------------------------------------------------------

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document file not found",
        )

    # --------------------------------------------------------
    # 6. ENSURE FILE IS INSIDE PRIVATE STORAGE
    # --------------------------------------------------------

    resolved_path = file_path.resolve()

    if resolved_path.parent != storage_dir:
        raise HTTPException(
            status_code=404,
            detail="Document file not found",
        )

    # --------------------------------------------------------
    # 7. RETURN AUTHORIZED DOCUMENT
    # --------------------------------------------------------

    return FileResponse(
        path=file_path,
        media_type=row["media_type"],
        filename=row["original_filename"],
        content_disposition_type="attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
