#!/usr/bin/env bash
# Restore PostgreSQL (+ optionally MinIO) from a backup created by scripts/backup.sh.
# Usage: bash scripts/restore.sh backups/db-YYYY-MM-DD.sql.gz [--minio-dir ./backups/minio-job-agent-private]
# WARNING: overwrites the current database. Workers are stopped first.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "usage: bash scripts/restore.sh <db-backup.sql.gz> [--minio-dir <dir>]" >&2
  exit 2
fi
DB_FILE="$1"
MINIO_DIR=""
if [ "${2:-}" = "--minio-dir" ]; then
  MINIO_DIR="${3:?missing minio dir}"
fi
if [ ! -f "${DB_FILE}" ]; then
  echo "backup file not found: ${DB_FILE}" >&2
  exit 1
fi

echo "==> stopping workers (database must be idle)"
docker compose stop orchestrator job-discovery job-matching cv-generator application-analyzer browser-agent api

echo "==> restoring PostgreSQL from ${DB_FILE}"
gunzip -c "${DB_FILE}" | docker compose exec -T postgres psql -U "${POSTGRES_USER:-jobagent}" "${POSTGRES_DB:-jobagent}"

if [ -n "${MINIO_DIR}" ]; then
  if ! command -v mc >/dev/null 2>&1; then
    echo "ERROR: --minio-dir given but 'mc' client not found." >&2
    exit 1
  fi
  echo "==> restoring MinIO bucket from ${MINIO_DIR}"
  mc alias set local http://127.0.0.1:9001 "${MINIO_ACCESS_KEY:?set MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY:?set MINIO_SECRET_KEY}" >/dev/null
  mc mirror --overwrite "${MINIO_DIR}" "local/${MINIO_BUCKET:-job-agent-private}"
fi

echo "==> restarting workers"
docker compose start api orchestrator job-discovery job-matching cv-generator application-analyzer browser-agent

echo "restore complete. Verify with: curl -s http://127.0.0.1:8000/health"
