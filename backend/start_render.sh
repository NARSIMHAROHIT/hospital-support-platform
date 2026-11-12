#!/usr/bin/env bash
set -euo pipefail

echo "Starting Hospital Platform API..."

# Require explicitly configured cloud storage paths
: "${HOSPITAL_DB_PATH:?HOSPITAL_DB_PATH is required}"
: "${MEDICAL_FILES_DIR:?MEDICAL_FILES_DIR is required}"

mkdir -p "$(dirname "$HOSPITAL_DB_PATH")"
mkdir -p "$MEDICAL_FILES_DIR"

# Initialize a new demo database, or verify an initialized one
python -m scripts.init_demo_database

# Prepare fictional doctors and appointment slots
python -m scripts.add_doctor_accounts
python -c "from scripts.seed_doctor_schedules import seed; seed()"

# Create fictional accounts using Render environment passwords
python -m scripts.seed_cloud_demo_users

echo "Starting FastAPI server..."

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}"
