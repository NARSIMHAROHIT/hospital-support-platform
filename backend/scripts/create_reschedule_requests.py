
from contextlib import closing

from app.core.database import get_db


def main():
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reschedule_requests (
                request_id TEXT PRIMARY KEY,

                appointment_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,

                original_slot_id TEXT NOT NULL,
                requested_slot_id TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (
                        status IN (
                            'pending',
                            'approved',
                            'rejected',
                            'cancelled'
                        )
                    ),

                created_at TEXT NOT NULL,
                decided_at TEXT,

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(appointment_id),

                FOREIGN KEY (patient_id)
                    REFERENCES patients(patient_id),

                FOREIGN KEY (doctor_id)
                    REFERENCES doctors(doctor_id),

                FOREIGN KEY (original_slot_id)
                    REFERENCES doctor_slots(slot_id),

                FOREIGN KEY (requested_slot_id)
                    REFERENCES doctor_slots(slot_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS
                one_pending_request_per_appointment
            ON reschedule_requests(appointment_id)
            WHERE status = 'pending';

            CREATE INDEX IF NOT EXISTS
                idx_reschedule_patient
            ON reschedule_requests(patient_id, created_at);

            CREATE INDEX IF NOT EXISTS
                idx_reschedule_doctor
            ON reschedule_requests(doctor_id, status);
        """)

        conn.commit()

    print("Reschedule request tables are ready.")


if __name__ == "__main__":
    main()
