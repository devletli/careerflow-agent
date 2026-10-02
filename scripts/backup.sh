#!/usr/bin/env bash
# PostgreSQL + MinIO backup for a single-host Docker Compose deployment.
# Usage: bash scripts/backup.sh   (or: make backup)
# Output: backups/db-YYYY-MM-DD.sql.gz + backups/minio-job-agent-private/
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

STAMP="$(date +%F)"
DB_FILE="backups/db-${STAMP}.sql.gz"

echo "==> PostgreSQL dump -> ${DB_FILE}"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-jobagent}" "${POSTGRES_DB:-jobagent}" | gzip > "${DB_FILE}"
echo "wrote ${DB_FILE} ($(du -h "${DB_FILE}" | cut -f1))"

if command -v mc >/dev/null 2>&1; then
  echo "==> MinIO bucket mirror -> backups/minio-job-agent-private/"
  mc alias set local http://127.0.0.1:9001 "${MINIO_ACCESS_KEY:?set MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY:?set MINIO_SECRET_KEY}" >/dev/null
  mc mirror --overwrite "local/${MINIO_BUCKET:-job-agent-private}" ./backups/minio-job-agent-private
else
  echo "WARNING: 'mc' client not found; skipping MinIO bucket mirror."
  echo "See https://min.io/docs/minio/linux/reference/minio-mc.html then re-run."
fi

echo "backup complete."
