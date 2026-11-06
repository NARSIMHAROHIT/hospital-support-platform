
from fastapi import FastAPI
from pydantic import BaseModel, Field
from uuid import uuid4

app = FastAPI(title="Hospital Patient Support API")

class PatientQuery(BaseModel):
    patient_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)

queries = []

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
    queries.append(ticket)
    return ticket

@app.get("/queries")
def get_queries():
    return queries
