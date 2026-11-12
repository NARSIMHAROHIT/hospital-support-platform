
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.permissions import require_admin
from app.routers.appointments import check_request_origin


router = APIRouter(
    prefix="/admin/care-team",
    tags=["Care Team Management"],
)


class AssignmentCreate(BaseModel):
    patient_id: str = Field(min_length=1)
    staff_user_id: str = Field(min_length=1)


def validate_staff(conn, staff_user_id):
    staff = conn.execute("""
        SELECT
            u.user_id,
            u.role,
            u.is_active,
            u.doctor_id,
            d.is_active AS doctor_active
        FROM users u
        LEFT JOIN doctors d
          ON d.doctor_id = u.doctor_id
        WHERE u.user_id = ?
    """, (staff_user_id,)).fetchone()

    if staff is None:
        raise HTTPException(
            status_code=404,
            detail="Staff account not found",
        )

    if staff["role"] not in ("doctor", "nurse"):
        raise HTTPException(
            status_code=422,
            detail="Only doctors and nurses can join a care team",
        )

    if staff["is_active"] != 1:
        raise HTTPException(
            status_code=409,
            detail="Staff account is inactive",
        )

    if staff["role"] == "doctor":
        if (
            not staff["doctor_id"]
            or staff["doctor_active"] != 1
        ):
            raise HTTPException(
                status_code=409,
                detail="Doctor account is not active or linked",
            )

    return staff


@router.post("/assignments", status_code=201)
def create_assignment(
    payload: AssignmentCreate,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    admin_id = admin.get("user_id")

    if not admin_id:
        raise HTTPException(
            status_code=403,
            detail="Administrator identity required",
        )

    assignment_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        patient = conn.execute("""
            SELECT patient_id
            FROM patients
            WHERE patient_id = ?
        """, (payload.patient_id,)).fetchone()

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="Patient not found",
            )

        staff = validate_staff(
            conn,
            payload.staff_user_id,
        )

        existing = conn.execute("""
            SELECT assignment_id
            FROM care_team_assignments
            WHERE patient_id = ?
              AND staff_user_id = ?
              AND revoked_at IS NULL
        """, (
            payload.patient_id,
            payload.staff_user_id,
        )).fetchone()

        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Staff member is already assigned",
            )

        try:
            conn.execute("""
                INSERT INTO care_team_assignments (
                    assignment_id,
                    patient_id,
                    staff_user_id,
                    assigned_by_user_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                assignment_id,
                payload.patient_id,
                payload.staff_user_id,
                admin_id,
                created_at,
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Unable to create care-team assignment",
            )

    return {
        "assignment_id": assignment_id,
        "patient_id": payload.patient_id,
        "staff_user_id": payload.staff_user_id,
        "staff_role": staff["role"],
        "created_at": created_at,
        "status": "active",
    }


@router.get("/assignments")
def list_assignments(
    patient_id: str | None = None,
    admin=Depends(require_admin),
):
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                c.assignment_id,
                c.patient_id,
                c.staff_user_id,
                u.email AS staff_email,
                u.role AS staff_role,
                c.assigned_by_user_id,
                c.created_at,
                c.revoked_at,
                c.revoked_by_user_id
            FROM care_team_assignments c
            JOIN users u
              ON u.user_id = c.staff_user_id
            WHERE (? IS NULL OR c.patient_id = ?)
            ORDER BY
                c.created_at DESC,
                c.assignment_id DESC
        """, (patient_id, patient_id)).fetchall()

    return [
        {
            **dict(row),
            "status": (
                "revoked"
                if row["revoked_at"] is not None
                else "active"
            ),
        }
        for row in rows
    ]


@router.patch("/assignments/{assignment_id}/revoke")
def revoke_assignment(
    assignment_id: str,
    admin=Depends(require_admin),
    _origin=Depends(check_request_origin),
):
    admin_id = admin.get("user_id")

    if not admin_id:
        raise HTTPException(
            status_code=403,
            detail="Administrator identity required",
        )

    revoked_at = datetime.now(timezone.utc).isoformat()

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        assignment = conn.execute("""
            SELECT assignment_id, revoked_at
            FROM care_team_assignments
            WHERE assignment_id = ?
        """, (assignment_id,)).fetchone()

        if assignment is None:
            raise HTTPException(
                status_code=404,
                detail="Assignment not found",
            )

        if assignment["revoked_at"] is not None:
            raise HTTPException(
                status_code=409,
                detail="Assignment has already been revoked",
            )

        updated = conn.execute("""
            UPDATE care_team_assignments
            SET
                revoked_at = ?,
                revoked_by_user_id = ?
            WHERE assignment_id = ?
              AND revoked_at IS NULL
        """, (
            revoked_at,
            admin_id,
            assignment_id,
        ))

        if updated.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Unable to revoke assignment",
            )

        conn.commit()

    return {
        "assignment_id": assignment_id,
        "status": "revoked",
        "revoked_at": revoked_at,
    }
