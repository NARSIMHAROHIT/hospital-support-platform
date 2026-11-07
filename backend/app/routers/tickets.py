
from contextlib import closing
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core.database import get_db
from app.schemas.tickets import (
    PatientQuery,
    StatusUpdate,
    PriorityUpdate,
    AssignmentUpdate,
)

router = APIRouter(tags=["Support Tickets"])


@router.post("/queries", status_code=201)
def create_query(query: PatientQuery):
    ticket = {
        "ticket_id": str(uuid4()),
        "patient_id": query.patient_id,
        "category": query.category,
        "question": query.question,
        "status": "open",
    }

    with closing(get_db()) as conn:
        conn.execute("""
            INSERT INTO queries
            (ticket_id, patient_id, category, question, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            ticket["ticket_id"],
            ticket["patient_id"],
            ticket["category"],
            ticket["question"],
            ticket["status"]
        ))
        conn.commit()

    return ticket


@router.get("/queries")
def list_queries():
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM queries"
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/queries/{ticket_id}")
def get_query(ticket_id: str):
    with closing(get_db()) as conn:
        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    if row is None:
        raise HTTPException(404, "Ticket not found")

    return dict(row)


@router.patch("/queries/{ticket_id}")
def update_query(ticket_id: str, change: StatusUpdate):
    with closing(get_db()) as conn:
        cursor = conn.execute("""
            UPDATE queries
            SET status = ?
            WHERE ticket_id = ?
        """, (
            change.status,
            ticket_id
        ))

        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


@router.patch("/queries/{ticket_id}/priority")
def update_priority(ticket_id: str, change: PriorityUpdate):
    with closing(get_db()) as conn:
        cursor = conn.execute("""
            UPDATE queries
            SET priority = ?,
                updated_at = strftime(
                    '%Y-%m-%dT%H:%M:%fZ', 'now'
                )
            WHERE ticket_id = ?
        """, (
            change.priority,
            ticket_id
        ))

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


@router.patch("/queries/{ticket_id}/assignment")
def update_assignment(
    ticket_id: str,
    change: AssignmentUpdate
):
    with closing(get_db()) as conn:
        cursor = conn.execute("""
            UPDATE queries
            SET department = ?,
                assigned_to = ?,
                updated_at = strftime(
                    '%Y-%m-%dT%H:%M:%fZ', 'now'
                )
            WHERE ticket_id = ?
        """, (
            change.department,
            change.assigned_to,
            ticket_id
        ))

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


@router.get("/dashboard/stats")
def dashboard_stats():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) AS total
            FROM queries
            GROUP BY status
        """).fetchall()

    counts = {
        row["status"]: row["total"]
        for row in rows
    }

    return {
        "total": sum(counts.values()),
        "open": counts.get("open", 0),
        "in_progress": counts.get("in_progress", 0),
        "resolved": counts.get("resolved", 0)
    }
