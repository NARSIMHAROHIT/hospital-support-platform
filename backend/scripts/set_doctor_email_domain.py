
import argparse
import re
from contextlib import closing

from app.core.database import get_db


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--domain",
        required=True,
        help="Organization email domain",
    )

    args = parser.parse_args()
    domain = args.domain.lower().strip().lstrip("@")

    if not re.fullmatch(
        r"[a-z0-9-]+(?:\.[a-z0-9-]+)+",
        domain,
    ):
        raise SystemExit("Invalid domain format")

    with closing(get_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        doctors = conn.execute("""
            SELECT
                u.user_id,
                u.email,
                d.full_name
            FROM users u
            JOIN doctors d
              ON u.doctor_id = d.doctor_id
            WHERE u.role = 'doctor'
            ORDER BY d.full_name
        """).fetchall()

        try:
            for doctor in doctors:
                # Preserve each doctor's existing local-part.
                local_part = doctor["email"].split("@")[0]
                new_email = f"{local_part}@{domain}"

                conn.execute("""
                    UPDATE users
                    SET email = ?
                    WHERE user_id = ?
                      AND role = 'doctor'
                """, (
                    new_email,
                    doctor["user_id"],
                ))

                print(
                    doctor["full_name"],
                    "->",
                    new_email,
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise


if __name__ == "__main__":
    main()
