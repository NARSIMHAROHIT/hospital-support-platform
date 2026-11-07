
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Pages"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(
        BASE_DIR / "static" / "index.html"
    )


@router.get("/patient-portal", include_in_schema=False)
def patient_portal():
    return FileResponse(
        BASE_DIR / "static" / "patient.html"
    )
