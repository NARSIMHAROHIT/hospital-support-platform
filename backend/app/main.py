
import sqlite3
from uuid import uuid4
from contextlib import closing
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Hospital Patient Support API", version="0.2.0")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "hospital.db"

Category = Literal[
    "appointment", "billing", "portal_access", "general"
]
Status = Literal["open", "in_progress", "resolved"]

class PatientQuery(BaseModel):
    patient_id: str = Field(min_length=1, max_length=50)
    category: Category
    question: str = Field(min_length=5, max_length=1000)

class StatusUpdate(BaseModel):
    status: Status

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

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

@app.get("/health")
def health():
    return {"status": "healthy", "service": "hospital-support"}

@app.post("/queries", status_code=201)
def create_query(query: PatientQuery):
    ticket = {
        "ticket_id": str(uuid4()),
        "patient_id": query.patient_id,
        "category": query.category,
        "question": query.question,
        "status": "open",
    }

    with closing(get_db()) as conn:
        conn.execute(
            """INSERT INTO queries
               (ticket_id, patient_id, category, question, status)
               VALUES (?, ?, ?, ?, ?)""",
            (
                ticket["ticket_id"], ticket["patient_id"],
                ticket["category"], ticket["question"], ticket["status"]
            )
        )
        conn.commit()

    return ticket

@app.get("/queries")
def list_queries():
    with closing(get_db()) as conn:
        rows = conn.execute("SELECT * FROM queries").fetchall()
        return [dict(row) for row in rows]

@app.get("/queries/{ticket_id}")
def get_query(ticket_id: str):
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT * FROM queries WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(404, "Ticket not found")

    return dict(row)

@app.patch("/queries/{ticket_id}")
def update_query(ticket_id: str, change: StatusUpdate):
    with closing(get_db()) as conn:
        cursor = conn.execute(
            "UPDATE queries SET status = ? WHERE ticket_id = ?",
            (change.status, ticket_id)
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        row = conn.execute(
            "SELECT * FROM queries WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()

    return dict(row)

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(BASE_DIR / "static" / "index.html")
