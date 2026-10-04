"""documents.application_id bos olan kayitlari job_id uzerinden baglar.

Tek seferlik veri duzeltmesidir (eski PATCH /api/v1/documents/backfill
route'unun yerini aldi; Gorev 4). Yalnizca job basina TAM OLARAK
1 application varsa baglar; belirsizleri atlar ve raporlar.
Idempotent: tekrar calistirmak ek degisiklik yapmaz.

Kullanim:
    python scripts/backfill_document_application_link.py [--dry-run]
    DATABASE_URL yoksa shared.config'taki deger kullanilir.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shared.config import settings
from shared.db.models import Application, Document


async def backfill(engine: AsyncEngine, dry_run: bool = False) -> dict:
    """Unlinked belgeleri baglar; sqlite+postgres uyumlu (ORM, ham SQL yok)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.application_id.is_(None))
            )
        ).scalars().all()
        job_ids = list({d.job_id for d in docs})
        apps_by_job: dict = {}
        if job_ids:
            rows = (
                await session.execute(
                    select(Application.job_id, Application.id).where(
                        Application.job_id.in_(job_ids)
                    )
                )
            ).all()
            for job_id, app_id in rows:
                apps_by_job.setdefault(job_id, []).append(app_id)
        linked = 0
        ambiguous = []
        for doc in docs:
            candidates = apps_by_job.get(doc.job_id, [])
            if len(candidates) == 1:
                if not dry_run:
                    doc.application_id = candidates[0]
                linked += 1
            else:
                ambiguous.append(str(doc.id))
        if not dry_run:
            await session.commit()
    return {"linked": linked, "ambiguous_unlinked": ambiguous}


def _default_url() -> str:
    import os

    url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _run(dry_run: bool) -> int:
    engine = create_async_engine(_default_url())
    try:
        result = await backfill(engine, dry_run=dry_run)
    finally:
        await engine.dispose()
    print(f"linked: {result['linked']}")  # noqa: T201 - CLI raporu
    print(f"ambiguous/unlinked: {len(result['ambiguous_unlinked'])}")  # noqa: T201 - CLI raporu
    for doc_id in result["ambiguous_unlinked"]:
        print(f"  skipped {doc_id}")  # noqa: T201 - CLI raporu
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
