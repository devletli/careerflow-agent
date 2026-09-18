"""
init_db.py – One-shot database initialisation:
  1. Wait for PostgreSQL to be available.
  2. Run Alembic migrations to head (via subprocess so alembic CLI env is correct).
  3. Ensure MinIO default bucket exists.
  4. Exit 0 on success.
"""
import asyncio
import logging
import subprocess
import sys

from shared.config import settings
from shared.db.session import check_db_health
from shared.infra.storage import MinIOClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("init-db")


async def wait_for_db(retries: int = 30, delay: float = 2.0) -> bool:
    for attempt in range(retries):
        ok = await check_db_health()
        if ok:
            logger.info("PostgreSQL is ready.")
            return True
        logger.info(f"Waiting for PostgreSQL... (attempt {attempt + 1}/{retries})")
        await asyncio.sleep(delay)
    return False


def run_migrations():
    """Runs alembic upgrade head via subprocess (uses the packaged alembic.ini)."""
    logger.info("Running Alembic migrations...")
    result = subprocess.run(
        ["python", "-m", "alembic", "-c", "/app/alembic.ini", "upgrade", "head"],
        capture_output=False,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Alembic migration failed (exit code {result.returncode})")
        sys.exit(result.returncode)
    logger.info("Alembic migrations applied successfully.")


def ensure_minio_bucket():
    try:
        client = MinIOClient()
        ok = client.ensure_bucket(settings.MINIO_BUCKET)
        if ok:
            logger.info(f"MinIO bucket '{settings.MINIO_BUCKET}' is ready.")
        else:
            logger.warning("MinIO bucket setup may have failed.")
    except Exception as e:
        logger.warning(f"Could not ensure MinIO bucket (non-fatal): {e}")


async def main():
    db_ready = await wait_for_db()
    if not db_ready:
        logger.error("PostgreSQL did not become ready in time. Exiting.")
        sys.exit(1)

    run_migrations()
    ensure_minio_bucket()

    logger.info("Database initialisation complete.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
