
from contextlib import closing

from fastapi import FastAPI

from app.core.database import get_db
from app.routers.auth import router as auth_router
from app.routers.patients import router as patients_router
from app.routers.doctors import router as doctors_router
from app.routers.appointments import router as appointments_router
from app.routers.tickets import router as tickets_router
from app.routers.pages import router as pages_router


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
