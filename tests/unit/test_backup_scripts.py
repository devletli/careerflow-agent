"""T7 backup/restore script tests (offline, static).

Verifies scripts/backup.sh + scripts/restore.sh exist and contain the
required steps (pg_dump/psql, mc mirror, fail-closed flags), and that the
runbook documents the restore + verification procedure.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "scripts" / "backup.sh"
RESTORE = ROOT / "scripts" / "restore.sh"
RUNBOOK = ROOT / "docs" / "runbook.md"
MAKEFILE = ROOT / "Makefile"


def test_backup_script_covers_db_and_objects():
    src = BACKUP.read_text(encoding="utf-8")
    assert src.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in src
    assert "pg_dump" in src and ".sql.gz" in src
    assert "mc mirror" in src


def test_restore_script_fails_closed_and_restarts_workers():
    src = RESTORE.read_text(encoding="utf-8")
    assert src.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in src
    assert "usage:" in src  # missing FILE prints usage + exits 2
    assert "docker compose stop" in src
    assert "psql" in src
    assert "docker compose start" in src
    assert "--minio-dir" in src


def test_makefile_delegates_to_scripts():
    src = MAKEFILE.read_text(encoding="utf-8")
    assert "scripts/backup.sh" in src
    assert "scripts/restore.sh" in src


def test_runbook_documents_restore_verification():
    src = RUNBOOK.read_text(encoding="utf-8")
    assert "scripts/restore.sh" in src
    assert "Restore verification" in src
    assert "/health" in src
    assert "test_backup_scripts" in src
