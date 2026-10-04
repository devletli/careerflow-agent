"""Gorev 4: backfill script testleri (route kalkti; script'e karsi yazildi).

Kapsar: tek-app job baglanir, appsiz job atlanir, cok-app belirsizlik
atlanir, --dry-run degisiklik yapmaz, ikinci calisma idempotent'tir.
"""
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = ROOT / "scripts" / "backfill_document_application_link.py"
    spec = importlib.util.spec_from_file_location("careerflow_backfill", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["careerflow_backfill"] = module
    spec.loader.exec_module(module)
    return module


_script = _load_script()

from shared.db.models import Application, Base, Document, Job  # noqa: E402


@pytest.fixture()
async def engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=eng, expire_on_commit=False)
    async with maker() as s:
        job1 = Job(
            id=uuid4(), source="manual", source_job_id="bf-1", company="Acme",
            title="DevOps", url="https://acme.example/1",
            job_fingerprint="fp-bf-1", status="NORMALIZED",
        )
        job2 = Job(
            id=uuid4(), source="manual", source_job_id="bf-2", company="Globex",
            title="Backend", url="https://globex.example/2",
            job_fingerprint="fp-bf-2", status="NORMALIZED",
        )
        job3 = Job(
            id=uuid4(), source="manual", source_job_id="bf-3", company="Initech",
            title="SRE", url="https://initech.example/3",
            job_fingerprint="fp-bf-3", status="NORMALIZED",
        )
        s.add_all([job1, job2, job3])
        await s.flush()
        app1 = Application(
            id=uuid4(), job_id=job1.id, candidate_id="c",
            application_fingerprint="fp-app-bf-1", status="READY_TO_APPLY",
        )
        app3a = Application(
            id=uuid4(), job_id=job3.id, candidate_id="c",
            application_fingerprint="fp-app-bf-3a", status="READY_TO_APPLY",
        )
        app3b = Application(
            id=uuid4(), job_id=job3.id, candidate_id="c",
            application_fingerprint="fp-app-bf-3b", status="READY_TO_APPLY",
        )
        s.add_all([app1, app3a, app3b])
        await s.flush()
        orphan = Document(
            id=uuid4(), job_id=job1.id, application_id=None, type="cv",
            language="en", version=1, minio_bucket="b", minio_key="k/1.pdf",
            mime_type="application/pdf", content_hash="h1",
        )
        noapp = Document(
            id=uuid4(), job_id=job2.id, application_id=None, type="cv",
            language="en", version=1, minio_bucket="b", minio_key="k/2.pdf",
            mime_type="application/pdf", content_hash="h2",
        )
        amb = Document(
            id=uuid4(), job_id=job3.id, application_id=None, type="cv",
            language="en", version=1, minio_bucket="b", minio_key="k/3.pdf",
            mime_type="application/pdf", content_hash="h3",
        )
        s.add_all([orphan, noapp, amb])
        await s.commit()
        ids = {
            "app1": app1.id, "orphan": orphan.id,
            "noapp": noapp.id, "amb": amb.id,
        }
    yield eng, ids
    await eng.dispose()


async def _app_of(engine, doc_id):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as s:
        doc = await s.get(Document, doc_id)
        return doc.application_id


def test_links_single_and_skips_ambiguous(engine):
    eng, ids = engine

    async def scenario():
        return await _script.backfill(eng, dry_run=False)

    import asyncio

    result = asyncio.run(scenario())
    assert result["linked"] == 1
    assert len(result["ambiguous_unlinked"]) == 2

    async def check():
        assert await _app_of(eng, ids["orphan"]) == ids["app1"]
        assert await _app_of(eng, ids["noapp"]) is None
        assert await _app_of(eng, ids["amb"]) is None

    asyncio.run(check())


def test_dry_run_changes_nothing(engine):
    eng, ids = engine

    async def scenario():
        return await _script.backfill(eng, dry_run=True)

    import asyncio

    result = asyncio.run(scenario())
    assert result["linked"] == 1  # baglanABILECEK sayisi raporlanir

    async def check():
        assert await _app_of(eng, ids["orphan"]) is None

    asyncio.run(check())


def test_second_run_is_idempotent(engine):
    import asyncio

    eng, _ = engine
    asyncio.run(_script.backfill(eng, dry_run=False))
    result = asyncio.run(_script.backfill(eng, dry_run=False))
    assert result["linked"] == 0
