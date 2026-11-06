
import sqlite3
from uuid import uuid4
from contextlib import closing

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Hospital Patient Support API")

DB_PATH = "hospital.db"

class PatientQuery(BaseModel):
    patient_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)

def get_db():
    return sqlite3.connect(DB_PATH)

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
        "status": "open"
    }

    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO queries VALUES (?, ?, ?, ?, ?)",
            tuple(ticket.values())
        )
        conn.commit()

    return ticket

@app.get("/queries")
def list_queries():
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM queries").fetchall()
        return [dict(row) for row in rows]

@app.get("/queries/{ticket_id}")
def get_query(ticket_id: str):
    with closing(get_db()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM queries WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return dict(row)
