# Operations Runbook

Minimal backup/restore procedures for a single-host Docker Compose deployment.
All commands run from the repository root with the stack up
(`docker compose up -d`).

## PostgreSQL backup

```bash
make backup
# equivalent: bash scripts/backup.sh
```

This writes a compressed dump to `backups/db-YYYY-MM-DD.sql.gz`
(`pg_dump` inside the `postgres` container, host Postgres port is not
published — use `docker compose exec`, not a local `psql`).

## PostgreSQL restore

Restore **overwrites** the current database. Stop the workers first so
nothing writes mid-restore:

```bash
make restore FILE=backups/db-YYYY-MM-DD.sql.gz
# equivalent: bash scripts/restore.sh backups/db-YYYY-MM-DD.sql.gz
# with MinIO objects: bash scripts/restore.sh backups/db-YYYY-MM-DD.sql.gz --minio-dir ./backups/minio-job-agent-private
```

The script stops the workers first (nothing may write mid-restore),
restores the dump, then restarts the workers.

## Restore verification

After any restore, confirm the stack is healthy before resuming:

```bash
curl -s http://127.0.0.1:8000/health
docker compose ps
python -m pytest tests/unit/test_backup_scripts.py -q
```

Expected: `/health` returns `{"status": "ok", ...}`, all services
`Up`, and the backup-script test passes (it checks that
`scripts/backup.sh` / `scripts/restore.sh` contain the required
`pg_dump` / `psql` / `mc mirror` steps and fail closed on missing
input). Then spot-check the dashboard at `http://localhost:3000`
(Jobs / Applications counts look plausible).

## MinIO bucket backup

The `mc` client is not bundled with the stack. Install it once
(see https://min.io/docs/minio/linux/reference/minio-mc.html), then:

```bash
mc alias set local http://127.0.0.1:9001 <MINIO_ACCESS_KEY> <MINIO_SECRET_KEY>
mc mirror --overwrite local/job-agent-private ./backups/minio-job-agent-private
```

Restore with the arguments reversed:

```bash
mc mirror --overwrite ./backups/minio-job-agent-private local/job-agent-private
```

Volume-level alternative: stop the stack and back up the named volumes
(`postgres_data`, `minio_data`, `redis_data`) with your host backup tool.

## Document-application backfill

One-shot data fix (replaces the removed `PATCH /api/v1/documents/backfill`
route). Links unlinked documents via `job_id` only where exactly one
application exists for the job; ambiguous rows are reported and skipped:

```bash
python scripts/backfill_document_application_link.py --dry-run
python scripts/backfill_document_application_link.py
```

## API key rotation

1. Generate a new key (32+ random characters).
2. Set the same value in `.env` (`API_KEY=...`).
3. Recreate the affected services so both sides pick it up:
   `docker compose up -d api frontend`.
4. Verify: `curl -i http://127.0.0.1:8000/health` → 200 (public),
   `curl -i http://127.0.0.1:8000/api/v1/status` → 401 without
   `X-API-Key`, 200 with the new key.
5. Old keys stop working immediately — there is no grace period.
