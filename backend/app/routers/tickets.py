
from contextlib import closing
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.database import get_db
from app.core.permissions import require_admin, require_patient

from app.schemas.tickets import (
    PatientQuery,
    StatusUpdate,
    PriorityUpdate,
    AssignmentUpdate,
    MyTicketCreate,
)


router = APIRouter(tags=["Support Tickets"])


# ==================================================
# 1. SECURITY
# ==================================================

# Allowed origins during local development.
ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


def check_request_origin(request: Request):
    """Basic origin protection for modifying requests."""
    origin = request.headers.get("origin")

    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Request origin not allowed",
        )


# ==================================================
# 2. ADMIN: CREATE SUPPORT TICKET
# ==================================================

@router.post("/queries", status_code=201)
def create_query(
    query: PatientQuery,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
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
            ticket["status"],
        ))

        conn.commit()

    return ticket


# ==================================================
# 3. ADMIN: LIST ALL TICKETS
# ==================================================

@router.get("/queries")
def list_queries(
    admin=Depends(require_admin),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM queries
            ORDER BY created_at DESC
        """).fetchall()

    return [dict(row) for row in rows]


# ==================================================
# 4. ADMIN: VIEW ONE TICKET
# ==================================================

@router.get("/queries/{ticket_id}")
def get_query(
    ticket_id: str,
    admin=Depends(require_admin),
):
    with closing(get_db()) as conn:
        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    return dict(row)


# ==================================================
# 5. ADMIN: UPDATE TICKET STATUS
# ==================================================

@router.patch("/queries/{ticket_id}")
def update_query(
    ticket_id: str,
    change: StatusUpdate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    with closing(get_db()) as conn:
        cursor = conn.execute("""
            UPDATE queries
            SET status = ?,
                updated_at = strftime(
                    '%Y-%m-%dT%H:%M:%fZ', 'now'
                )
            WHERE ticket_id = ?
        """, (
            change.status,
            ticket_id,
        ))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Ticket not found",
            )

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


# ==================================================
# 6. ADMIN: UPDATE PRIORITY
# ==================================================

@router.patch("/queries/{ticket_id}/priority")
def update_priority(
    ticket_id: str,
    change: PriorityUpdate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
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
            ticket_id,
        ))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Ticket not found",
            )

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


# ==================================================
# 7. ADMIN: ASSIGN SUPPORT STAFF
# ==================================================

@router.patch("/queries/{ticket_id}/assignment")
def update_assignment(
    ticket_id: str,
    change: AssignmentUpdate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
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
            ticket_id,
        ))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Ticket not found",
            )

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM queries
            WHERE ticket_id = ?
        """, (ticket_id,)).fetchone()

    return dict(row)


# ==================================================
# 8. ADMIN: DASHBOARD STATISTICS
# ==================================================

@router.get("/dashboard/stats")
def dashboard_stats(
    admin=Depends(require_admin),
):
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
        "resolved": counts.get("resolved", 0),
    }


# ==================================================
# 9. PATIENT: CREATE OWN SUPPORT TICKET
# ==================================================

@router.post("/my/queries", status_code=201)
def create_my_query(
    query: MyTicketCreate,
    user=Depends(require_patient),
    _origin=Depends(check_request_origin),
):
    ticket = {
        "ticket_id": str(uuid4()),
        "patient_id": user["patient_id"],
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
            ticket["status"],
        ))

        conn.commit()

    return ticket


# ==================================================
# 10. PATIENT: VIEW OWN SUPPORT TICKETS
# ==================================================

@router.get("/my/queries")
def list_my_queries(
    user=Depends(require_patient),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                ticket_id,
                category,
                question,
                status,
                priority,
                department,
                created_at,
                updated_at
            FROM queries
            WHERE patient_id = ?
            ORDER BY created_at DESC
        """, (user["patient_id"],)).fetchall()

    return [dict(row) for row in rows]


# ==================================================
# 11. PATIENT: VIEW ONE OWN TICKET
# ==================================================

@router.get("/my/queries/{ticket_id}")
def get_my_query(
    ticket_id: str,
    user=Depends(require_patient),
):
    with closing(get_db()) as conn:
        row = conn.execute("""
            SELECT
                ticket_id,
                category,
                question,
                status,
                priority,
                department,
                created_at,
                updated_at
            FROM queries
            WHERE ticket_id = ?
              AND patient_id = ?
        """, (
            ticket_id,
            user["patient_id"],
        )).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    return dict(row)
