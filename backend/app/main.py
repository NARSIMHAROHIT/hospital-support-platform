
import sqlite3
from uuid import uuid4
from contextlib import closing
from pathlib import Path
from typing import Literal
import secrets
import hashlib
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from pydantic import EmailStr
from typing import Literal
from fastapi import Cookie, Response
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from pathlib import Path
from fastapi.responses import FileResponse


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

class PriorityUpdate(BaseModel):
    priority: Literal["low", "medium", "high"]

class AssignmentUpdate(BaseModel):
    department: Literal[
        "general", "billing", "appointments", "it_support"
    ]
    assigned_to: str | None = Field(
        default=None, max_length=50
    )

class PatientCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=25)


class DoctorCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    specialization: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)


class DoctorSlotCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime

class AvailabilityCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AppointmentCreate(BaseModel):
    patient_id: str
    doctor_id: str
    slot_id: str

class AppointmentReschedule(BaseModel):
    new_slot_id: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


password_hasher = PasswordHasher()
SESSION_COOKIE = "hospital_session"

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



@app.patch("/queries/{ticket_id}/priority")
def update_priority(ticket_id: str, change: PriorityUpdate):
    with closing(get_db()) as conn:
        cursor = conn.execute(
            """
            UPDATE queries
            SET priority = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE ticket_id = ?
            """,
            (change.priority, ticket_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        conn.commit()

        row = conn.execute(
            "SELECT * FROM queries WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()

    return dict(row)


@app.patch("/queries/{ticket_id}/assignment")
def update_assignment(ticket_id: str, change: AssignmentUpdate):
    with closing(get_db()) as conn:
        cursor = conn.execute(
            """
            UPDATE queries
            SET department = ?,
                assigned_to = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE ticket_id = ?
            """,
            (change.department, change.assigned_to, ticket_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(404, "Ticket not found")

        conn.commit()

        row = conn.execute(
            "SELECT * FROM queries WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()

    return dict(row)



@app.get("/dashboard/stats")
def dashboard_stats():
    with closing(get_db()) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM queries
            GROUP BY status
            """
        ).fetchall()

    counts = {row["status"]: row["total"] for row in rows}

    return {
        "total": sum(counts.values()),
        "open": counts.get("open", 0),
        "in_progress": counts.get("in_progress", 0),
        "resolved": counts.get("resolved", 0)
    }



@app.post("/patients", status_code=201)
def create_patient(patient: PatientCreate):
    patient_id = str(uuid4())

    with closing(get_db()) as conn:
        try:
            conn.execute("""
                INSERT INTO patients
                (patient_id, full_name, email, phone)
                VALUES (?, ?, ?, ?)
            """, (
                patient_id,
                patient.full_name,
                str(patient.email),
                patient.phone
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="Patient email already exists"
            )

    return {
        "patient_id": patient_id,
        "full_name": patient.full_name,
        "email": str(patient.email),
        "phone": patient.phone
    }


@app.get("/patients")
def list_patients():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT patient_id, full_name, email, phone
            FROM patients
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]


@app.post("/doctors", status_code=201)
def create_doctor(doctor: DoctorCreate):
    doctor_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("""
            INSERT INTO doctors
            (doctor_id, full_name, specialization, department)
            VALUES (?, ?, ?, ?)
        """, (
            doctor_id,
            doctor.full_name,
            doctor.specialization,
            doctor.department
        ))
        conn.commit()

    return {
        "doctor_id": doctor_id,
        "full_name": doctor.full_name,
        "specialization": doctor.specialization,
        "department": doctor.department,
        "is_active": True
    }


@app.get("/doctors")
def list_doctors():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT * FROM doctors
            WHERE is_active = 1
            ORDER BY full_name
        """).fetchall()

    return [dict(row) for row in rows]


@app.post("/doctors/{doctor_id}/slots", status_code=201)
def create_doctor_slot(doctor_id: str, slot: AvailabilityCreate):
    if (
        slot.starts_at.utcoffset() is None
        or slot.ends_at.utcoffset() is None
    ):
        raise HTTPException(422, "Timezone offset required")

    start = slot.starts_at.astimezone(timezone.utc).isoformat()
    end = slot.ends_at.astimezone(timezone.utc).isoformat()

    if slot.ends_at <= slot.starts_at:
        raise HTTPException(422, "Invalid time range")

    slot_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        doctor = conn.execute(
            "SELECT 1 FROM doctors WHERE doctor_id = ? AND is_active = 1",
            (doctor_id,)
        ).fetchone()

        if doctor is None:
            raise HTTPException(404, "Active doctor not found")

        overlap = conn.execute("""
            SELECT 1 FROM doctor_slots
            WHERE doctor_id = ?
              AND starts_at < ?
              AND ends_at > ?
        """, (doctor_id, end, start)).fetchone()

        if overlap:
            raise HTTPException(409, "Slot overlaps existing schedule")

        conn.execute("""
            INSERT INTO doctor_slots
            (slot_id, doctor_id, starts_at, ends_at)
            VALUES (?, ?, ?, ?)
        """, (slot_id, doctor_id, start, end))
        conn.commit()

    return {
        "slot_id": slot_id,
        "doctor_id": doctor_id,
        "starts_at": start,
        "ends_at": end
    }


@app.get("/doctors/{doctor_id}/slots")
def get_available_slots(doctor_id: str):
    with closing(get_db()) as conn:
        rows = conn.execute("""
        SELECT s.*
        FROM doctor_slots s
        WHERE s.doctor_id = ?
        AND NOT EXISTS (
            SELECT 1
            FROM appointments a
            WHERE a.slot_id = s.slot_id
                AND a.status IN ('booked', 'completed')
        )
        ORDER BY s.starts_at
    """, (doctor_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/appointments", status_code=201)
def book_appointment(booking: AppointmentCreate):
    appointment_id = str(uuid4())

    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        patient = conn.execute(
            "SELECT 1 FROM patients WHERE patient_id = ?",
            (booking.patient_id,)
        ).fetchone()

        if patient is None:
            raise HTTPException(404, "Patient not found")

        slot = conn.execute("""
            SELECT s.slot_id
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (booking.slot_id, booking.doctor_id)).fetchone()

        if slot is None:
            raise HTTPException(404, "Doctor slot not found")

        try:
            conn.execute("""
                INSERT INTO appointments
                (appointment_id, patient_id, doctor_id, slot_id)
                VALUES (?, ?, ?, ?)
            """, (
                appointment_id, booking.patient_id,
                booking.doctor_id, booking.slot_id
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Slot already booked")

    return {
        "appointment_id": appointment_id,
        "patient_id": booking.patient_id,
        "doctor_id": booking.doctor_id,
        "slot_id": booking.slot_id,
        "status": "booked"
    }


@app.get("/appointments")
def list_appointments():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT a.appointment_id, a.status,
                   p.full_name AS patient,
                   d.full_name AS doctor,
                   d.specialization,
                   s.starts_at, s.ends_at
            FROM appointments a
            JOIN patients p ON a.patient_id = p.patient_id
            JOIN doctors d ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s ON a.slot_id = s.slot_id
            ORDER BY s.starts_at
        """).fetchall()

    return [dict(row) for row in rows]



@app.patch("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        appointment = conn.execute(
            """
            SELECT appointment_id, status
            FROM appointments
            WHERE appointment_id = ?
            """,
            (appointment_id,)
        ).fetchone()

        if appointment is None:
            raise HTTPException(404, "Appointment not found")

        if appointment["status"] != "booked":
            raise HTTPException(
                409, "Only booked appointments can be cancelled"
            )

        conn.execute(
            """
            UPDATE appointments
            SET status = 'cancelled'
            WHERE appointment_id = ?
            """,
            (appointment_id,)
        )
        conn.commit()

    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "message": "Appointment cancelled successfully"
    }



@app.patch("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: str,
    request: AppointmentReschedule
):
    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        # Find the existing appointment
        appointment = conn.execute("""
            SELECT appointment_id, doctor_id, slot_id, status
            FROM appointments
            WHERE appointment_id = ?
        """, (appointment_id,)).fetchone()

        if appointment is None:
            raise HTTPException(404, "Appointment not found")

        if appointment["status"] != "booked":
            raise HTTPException(
                409, "Only booked appointments can be rescheduled"
            )

        if appointment["slot_id"] == request.new_slot_id:
            raise HTTPException(
                409, "New slot must be different"
            )

        # Verify new slot belongs to same active doctor
        new_slot = conn.execute("""
            SELECT s.slot_id, s.starts_at, s.ends_at
            FROM doctor_slots s
            JOIN doctors d ON s.doctor_id = d.doctor_id
            WHERE s.slot_id = ?
              AND s.doctor_id = ?
              AND d.is_active = 1
        """, (
            request.new_slot_id,
            appointment["doctor_id"]
        )).fetchone()

        if new_slot is None:
            raise HTTPException(
                404, "New doctor slot not found"
            )

        # Reject past appointment times
        start_time = datetime.fromisoformat(
            new_slot["starts_at"]
        )

        if start_time <= datetime.now(timezone.utc):
            raise HTTPException(
                409, "Cannot reschedule into a past slot"
            )

        # Check if another active booking occupies the slot
        occupied = conn.execute("""
            SELECT 1
            FROM appointments
            WHERE slot_id = ?
              AND status IN ('booked', 'completed')
        """, (request.new_slot_id,)).fetchone()

        if occupied:
            raise HTTPException(
                409, "Requested slot is unavailable"
            )

        try:
            conn.execute("""
                UPDATE appointments
                SET slot_id = ?
                WHERE appointment_id = ?
            """, (
                request.new_slot_id,
                appointment_id
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(
                409, "Requested slot is unavailable"
            )

    return {
        "appointment_id": appointment_id,
        "status": "booked",
        "previous_slot_id": appointment["slot_id"],
        "new_slot_id": request.new_slot_id,
        "starts_at": new_slot["starts_at"],
        "ends_at": new_slot["ends_at"],
        "message": "Appointment rescheduled successfully"
    }




@app.post("/auth/login")
def login(credentials: LoginRequest, response: Response):
    with closing(get_db()) as conn:
        user = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ? AND is_active = 1
        """, (str(credentials.email),)).fetchone()

        # Same response for incorrect email or password
        if user is None:
            raise HTTPException(401, "Invalid credentials")

        try:
            password_hasher.verify(
                user["password_hash"],
                credentials.password
            )
        except (VerifyMismatchError, VerificationError):
            raise HTTPException(401, "Invalid credentials")

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()

        conn.execute("""
            INSERT INTO sessions
            (session_id, user_id, token_hash, expires_at)
            VALUES (?, ?, ?, ?)
        """, (
            str(uuid4()),
            user["user_id"],
            token_hash,
            expires_at
        ))
        conn.commit()

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=False,  # Local HTTP demo only
        samesite="lax",
        max_age=3600,
        path="/"
    )

    return {
        "message": "Login successful",
        "role": user["role"]
    }

def get_current_user(token: str | None):
    if not token:
        raise HTTPException(401, "Authentication required")

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with closing(get_db()) as conn:
        user = conn.execute("""
            SELECT u.user_id, u.patient_id,
                   u.email, u.role, s.expires_at
            FROM sessions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.token_hash = ?
              AND u.is_active = 1
        """, (token_hash,)).fetchone()

    if user is None:
        raise HTTPException(401, "Invalid session")

    if datetime.fromisoformat(
        user["expires_at"]
    ) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")

    return dict(user)


@app.get("/auth/me")
def my_profile(
    hospital_session: str | None = Cookie(default=None)
):
    user = get_current_user(hospital_session)

    return {
        "user_id": user["user_id"],
        "patient_id": user["patient_id"],
        "email": user["email"],
        "role": user["role"]
    }



@app.get("/my/appointments")
def my_appointments(
    hospital_session: str | None = Cookie(default=None)
):
    user = get_current_user(hospital_session)

    if user["role"] != "patient" or not user["patient_id"]:
        raise HTTPException(403, "Patient access required")

    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT
                a.appointment_id,
                a.status,
                d.full_name AS doctor,
                d.specialization,
                s.starts_at,
                s.ends_at
            FROM appointments a
            JOIN doctors d ON a.doctor_id = d.doctor_id
            JOIN doctor_slots s ON a.slot_id = s.slot_id
            WHERE a.patient_id = ?
            ORDER BY s.starts_at
        """, (user["patient_id"],)).fetchall()

    return [dict(row) for row in rows]



@app.post("/auth/logout")
def logout(
    response: Response,
    hospital_session: str | None = Cookie(default=None)
):
    if hospital_session:
        token_hash = hashlib.sha256(
            hospital_session.encode("utf-8")
        ).hexdigest()

        with closing(get_db()) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,)
            )
            conn.commit()

    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        samesite="lax"
    )

    return {"message": "Logged out successfully"}


@app.get("/patient-portal", include_in_schema=False)
def patient_portal():
    return FileResponse(
        Path(__file__).resolve().parent.parent / "static" / "patient.html"
    )