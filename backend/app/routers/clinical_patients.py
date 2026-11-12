
from contextlib import closing

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
)

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.care_access import (
    appointment_access_cutoff,
    authorize_record_action,
)


router = APIRouter(
    prefix="/clinical",
    tags=["Clinical Patients"],
)


def require_clinical_staff(
    hospital_session: str | None = Cookie(default=None),
):
    if not hospital_session:
        raise HTTPException(
            status_code=401,
            detail="Login required",
        )

    user = dict(get_current_user(hospital_session))

    if user.get("role") not in ("doctor", "nurse"):
        raise HTTPException(
            status_code=403,
            detail="Clinical staff access required",
        )

    if not user.get("user_id"):
        raise HTTPException(
            status_code=403,
            detail="Staff identity required",
        )

    if user["role"] == "doctor":
        if not user.get("doctor_id"):
            raise HTTPException(
                status_code=403,
                detail="Doctor account is not linked",
            )

        with closing(get_db()) as conn:
            doctor = conn.execute("""
                SELECT is_active
                FROM doctors
                WHERE doctor_id = ?
            """, (user["doctor_id"],)).fetchone()

        if doctor is None or doctor["is_active"] != 1:
            raise HTTPException(
                status_code=403,
                detail="Doctor account is inactive",
            )

    return user


def eligible_patients_query(user):
    """
    Build the access scope for this authenticated staff user.

    A doctor sees:
      - manually assigned patients
      - patients with eligible appointments

    A nurse sees:
      - manually assigned patients only
    """
    sql = """
        WITH eligible AS (
            SELECT
                c.patient_id,
                c.created_at AS assigned_at,
                'care_team' AS access_source
            FROM care_team_assignments c
            WHERE c.staff_user_id = ?
              AND c.revoked_at IS NULL
    """

    parameters = [user["user_id"]]

    if user["role"] == "doctor":
        sql += """
            UNION ALL

            SELECT
                a.patient_id,
                NULL AS assigned_at,
                'appointment' AS access_source
            FROM appointments a
            JOIN doctor_slots s
              ON s.slot_id = a.slot_id
            WHERE a.doctor_id = ?
              AND a.status IN ('booked', 'completed')
              AND datetime(s.ends_at) >= datetime(?)
        """

        parameters.extend([
            user["doctor_id"],
            appointment_access_cutoff(),
        ])

    sql += """
        )
    """

    return sql, parameters


@router.get("/my-patients")
def list_my_patients(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_clinical_staff),
):
    search = q.strip()
    scope_sql, scope_params = eligible_patients_query(user)

    with closing(get_db()) as conn:
        total = conn.execute(
            scope_sql + """
                SELECT COUNT(DISTINCT p.patient_id) AS total
                FROM eligible e
                JOIN patients p
                  ON p.patient_id = e.patient_id
                WHERE (
                    ? = ''
                    OR instr(lower(p.full_name), lower(?)) > 0
                )
            """,
            (*scope_params, search, search),
        ).fetchone()["total"]

        rows = conn.execute(
            scope_sql + """
                SELECT
                    p.patient_id,
                    p.full_name,
                    MIN(e.assigned_at) AS assigned_at,
                    CASE
                        WHEN MAX(
                            CASE
                                WHEN e.access_source = 'care_team'
                                THEN 1
                                ELSE 0
                            END
                        ) = 1
                        THEN 'care_team'
                        ELSE 'appointment'
                    END AS access_source
                FROM eligible e
                JOIN patients p
                  ON p.patient_id = e.patient_id
                WHERE (
                    ? = ''
                    OR instr(lower(p.full_name), lower(?)) > 0
                )
                GROUP BY p.patient_id, p.full_name
                ORDER BY lower(p.full_name), p.patient_id
                LIMIT ? OFFSET ?
            """,
            (
                *scope_params,
                search,
                search,
                limit,
                offset,
            ),
        ).fetchall()

        patients = []

        for row in rows:
            authorize_record_action(
                conn,
                user,
                row["patient_id"],
                "records:read",
            )
            patients.append(dict(row))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "patients": patients,
    }


@router.get("/my-patients/{patient_id}")
def get_my_patient(
    patient_id: str,
    user: dict = Depends(require_clinical_staff),
):
    with closing(get_db()) as conn:
        authorize_record_action(
            conn,
            user,
            patient_id,
            "records:read",
        )

        patient = conn.execute("""
            SELECT patient_id, full_name
            FROM patients
            WHERE patient_id = ?
        """, (patient_id,)).fetchone()

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="Patient not found",
            )

        manual = conn.execute("""
            SELECT created_at
            FROM care_team_assignments
            WHERE patient_id = ?
              AND staff_user_id = ?
              AND revoked_at IS NULL
            ORDER BY created_at
            LIMIT 1
        """, (
            patient_id,
            user["user_id"],
        )).fetchone()

        result = dict(patient)

        result["assigned_at"] = (
            manual["created_at"] if manual else None
        )

        result["access_source"] = (
            "care_team" if manual else "appointment"
        )

    return result
