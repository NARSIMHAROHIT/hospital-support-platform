
from contextlib import closing

from app.core.database import get_db


def main():
    with closing(get_db()) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS medical_history (
                history_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                category TEXT NOT NULL
                    CHECK (category IN (
                        'condition',
                        'allergy',
                        'surgery',
                        'family_history'
                    )),
                description TEXT NOT NULL,
                recorded_by_doctor_id TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                FOREIGN KEY (patient_id)
                    REFERENCES patients(patient_id),

                FOREIGN KEY (recorded_by_doctor_id)
                    REFERENCES doctors(doctor_id)
            );

            CREATE TABLE IF NOT EXISTS clinical_notes (
                note_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                appointment_id TEXT,
                note_type TEXT NOT NULL DEFAULT 'progress',
                observations TEXT NOT NULL,
                assessment TEXT,
                treatment_plan TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                FOREIGN KEY (patient_id)
                    REFERENCES patients(patient_id),

                FOREIGN KEY (doctor_id)
                    REFERENCES doctors(doctor_id),

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(appointment_id)
            );

            CREATE TABLE IF NOT EXISTS lab_reports (
                report_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                doctor_id TEXT,
                test_name TEXT NOT NULL,
                result_text TEXT,
                report_date TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                FOREIGN KEY (patient_id)
                    REFERENCES patients(patient_id),

                FOREIGN KEY (doctor_id)
                    REFERENCES doctors(doctor_id)
            );

            CREATE TABLE IF NOT EXISTS prescriptions (
                prescription_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                doctor_id TEXT NOT NULL,
                appointment_id TEXT,
                medication_name TEXT NOT NULL,
                dosage TEXT NOT NULL,
                frequency TEXT NOT NULL,
                duration TEXT,
                instructions TEXT,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

                FOREIGN KEY (patient_id)
                    REFERENCES patients(patient_id),

                FOREIGN KEY (doctor_id)
                    REFERENCES doctors(doctor_id),

                FOREIGN KEY (appointment_id)
                    REFERENCES appointments(appointment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_history_patient
                ON medical_history(patient_id);

            CREATE INDEX IF NOT EXISTS idx_notes_patient
                ON clinical_notes(patient_id);

            CREATE INDEX IF NOT EXISTS idx_labs_patient
                ON lab_reports(patient_id);

            CREATE INDEX IF NOT EXISTS idx_rx_patient
                ON prescriptions(patient_id);
        """)

        conn.commit()

    print("Medical records database tables created successfully.")


if __name__ == "__main__":
    main()
