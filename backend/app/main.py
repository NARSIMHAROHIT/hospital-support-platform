
from contextlib import closing

from fastapi import FastAPI

from app.core.database import get_db
from app.routers.auth import router as auth_router
from app.routers.patients import router as patients_router
from app.routers.doctors import router as doctors_router
from app.routers.appointments import router as appointments_router
from app.routers.tickets import router as tickets_router
from app.routers.pages import router as pages_router
from app.routers import reschedule_requests
from app.routers import doctor_portal
from app.routers import doctor_schedule_management
from app.routers import doctor_visits
from app.routers import registration
from app.routers import care_team_management
from app.routers import clinical_patients
from app.routers import nurse_invitations
from app.routers import medical_documents
from app.routers import doctor_documents
from app.routers import doctor_clinical_notes
from app.routers import patient_clinical_notes
from app.routers import clinical_note_sharing
from app.routers import patient_ai
from app.routers import ai_chat_memory

app = FastAPI(
    title="Hospital Patient Support API",
    version="0.3.0"
)


def initialize_db():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                ticket_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conn.commit()


initialize_db()


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "healthy",
        "service": "hospital-support"
    }


app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(doctors_router)
app.include_router(appointments_router)
app.include_router(tickets_router)
app.include_router(pages_router)
app.include_router(reschedule_requests.router)
app.include_router(doctor_portal.router)
app.include_router(doctor_schedule_management.router)
app.include_router(doctor_visits.router)
app.include_router(registration.router)
app.include_router(care_team_management.router)
app.include_router(clinical_patients.router)
app.include_router(nurse_invitations.router)
app.include_router(medical_documents.router)
app.include_router(doctor_documents.router)
app.include_router(doctor_clinical_notes.router)
app.include_router(patient_clinical_notes.router)
app.include_router(clinical_note_sharing.router)
app.include_router(patient_ai.router)
app.include_router(ai_chat_memory.router)