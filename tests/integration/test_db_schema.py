import pytest
import pytest_asyncio
from pathlib import Path
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError

from shared.db.models import (
    Base,
    Job,
    Document,
    Application,
    PipelineEvent,
)


@pytest_asyncio.fixture
async def test_session():
    # Use SQLite in-memory with aiosqlite for isolated fast testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_job_and_unique_constraint(test_session: AsyncSession):
    job1 = Job(
        id=uuid4(),
        source="workable",
        source_job_id="job-100",
        company="TechCorp",
        title="AI Engineer",
        url="https://workable.com/job-100",
        job_fingerprint="fp100",
        status="DISCOVERED",
    )
    test_session.add(job1)
    await test_session.commit()

    # Attempting duplicate (source, source_job_id) must raise IntegrityError
    job_dup = Job(
        id=uuid4(),
        source="workable",
        source_job_id="job-100",
        company="TechCorp",
        title="AI Engineer Duplicate",
        url="https://workable.com/job-100",
        job_fingerprint="fp101",
        status="DISCOVERED",
    )
    test_session.add(job_dup)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_application_and_unique_fingerprint(test_session: AsyncSession):
    job = Job(
        id=uuid4(),
        source="workable",
        source_job_id="job-200",
        company="TechCorp",
        title="DevOps Lead",
        url="https://workable.com/job-200",
        job_fingerprint="fp200",
        status="DISCOVERED",
    )
    test_session.add(job)
    await test_session.commit()

    app1 = Application(
        id=uuid4(),
        job_id=job.id,
        candidate_id="cand-1",
        application_fingerprint="app-fp-1",
        status="DISCOVERED",
    )
    test_session.add(app1)
    await test_session.commit()

    # Duplicate application fingerprint must fail
    app2 = Application(
        id=uuid4(),
        job_id=job.id,
        candidate_id="cand-1",
        application_fingerprint="app-fp-1",
        status="DISCOVERED",
    )
    test_session.add(app2)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_document_unique_constraint(test_session: AsyncSession):
    job_id = uuid4()
    job = Job(
        id=job_id,
        source="workable",
        source_job_id="job-300",
        company="TechCorp",
        title="DevOps Lead",
        url="https://workable.com/job-300",
        job_fingerprint="fp300",
        status="DISCOVERED",
    )
    test_session.add(job)
    await test_session.commit()

    doc1 = Document(
        id=uuid4(),
        job_id=job_id,
        type="cv",
        language="de",
        version=1,
        minio_bucket="job-agent-private",
        minio_key="cv/job-300/de/v1.pdf",
        content_hash="hash1",
    )
    test_session.add(doc1)
    await test_session.commit()

    # Same (job_id, type, language, version) must fail
    doc_dup = Document(
        id=uuid4(),
        job_id=job_id,
        type="cv",
        language="de",
        version=1,
        minio_bucket="job-agent-private",
        minio_key="cv/job-300/de/v1_dup.pdf",
        content_hash="hash2",
    )
    test_session.add(doc_dup)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


def test_dashboard_query_indexes_exist():
    """yama.md Faz 5-C: dashboard hot-path indexes must exist in metadata."""
    app_indexes = {ix.name for ix in Application.__table__.indexes}
    event_indexes = {ix.name for ix in PipelineEvent.__table__.indexes}
    doc_indexes = {ix.name for ix in Document.__table__.indexes}
    assert "ix_applications_status_updated" in app_indexes
    assert "ix_applications_job_id" in app_indexes  # Faz 4E
    assert "ix_documents_job_type" in doc_indexes  # Faz 4E
    assert "ix_pipeline_events_created_at" in event_indexes


def test_dashboard_queries_use_indexes():
    """EXPLAIN QUERY PLAN must show the new indexes serving dashboard shapes."""
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        plan_app = " ".join(
            row[3]
            for row in conn.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM applications "
                    "WHERE status = 'READY_TO_APPLY' ORDER BY updated_at LIMIT 10"
                )
            ).all()
        )
        assert "ix_applications_status_updated" in plan_app, plan_app
        plan_ev = " ".join(
            row[3]
            for row in conn.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM pipeline_events "
                    "ORDER BY created_at DESC LIMIT 50"
                )
            ).all()
        )
        assert "ix_pipeline_events_created_at" in plan_ev, plan_ev
        plan_app_job = " ".join(
            row[3]
            for row in conn.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM applications "
                    "WHERE job_id = '00000000-0000-0000-0000-000000000000'"
                )
            ).all()
        )
        assert "ix_applications_job_id" in plan_app_job, plan_app_job
        plan_doc = " ".join(
            row[3]
            for row in conn.execute(
                text("EXPLAIN QUERY PLAN SELECT id FROM documents WHERE job_id = '00000000-0000-0000-0000-000000000000' AND type = 'cv'")
            ).all()
        )
        assert "ix_documents_job_type" in plan_doc, plan_doc
    engine.dispose()


def test_alembic_revision_chain_valid():
    """Migration id'leri alembic_version VARCHAR(32)'ye sigar ve zincir kopsuzdur."""
    import re

    versions_dir = Path(__file__).resolve().parents[2] / "db" / "migrations" / "versions"
    revs = {}
    downs = {}
    for path in sorted(versions_dir.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision:\s*str\s*=\s*'([^']+)'", src, re.M).group(1)
        down = re.search(r"^down_revision.*=\s*'([^']+)'", src, re.M)
        assert len(rev) <= 32, f"{path.name}: revision id {len(rev)} chars > 32"
        revs[rev] = path.name
        downs[rev] = down.group(1) if down else None
    assert len(revs) >= 1
    heads = [r for r in revs if r not in set(downs.values())]
    assert len(heads) == 1, f"tek head beklenir: {heads}"
    seen = set()
    current = heads[0]
    while current is not None:
        assert current not in seen, "dongu var"
        seen.add(current)
        current = downs[current]
    assert seen == set(revs), "zincir disi revision var"


@pytest.mark.asyncio
async def test_pipeline_event_creation(test_session: AsyncSession):
    event_id = uuid4()
    ev = PipelineEvent(
        event_id=event_id,
        event_type="job.discovered.v1",
        version="v1",
        correlation_id="corr-1",
        idempotency_key=str(event_id),
        entity_id="job-1",
        entity_type="job",
        payload={"company": "Test"},
    )
    test_session.add(ev)
    await test_session.commit()

    # Unique event_id constraint
    ev_dup = PipelineEvent(
        event_id=event_id,
        event_type="job.discovered.v1",
        version="v1",
        correlation_id="corr-2",
        idempotency_key=str(uuid4()),
        entity_id="job-2",
        entity_type="job",
        payload={"company": "Test 2"},
    )
    test_session.add(ev_dup)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_pipeline_event_idempotency_key_unique(test_session: AsyncSession):
    """Faz 4A: ayni idempotency_key iki kez kaydedilemez (retry dedupe)."""
    key = f"cmd-{uuid4().hex}"
    test_session.add(
        PipelineEvent(
            event_id=uuid4(),
            event_type="job.discovered.v1",
            version="v1",
            correlation_id="corr-1",
            idempotency_key=key,
            entity_id="job-1",
            entity_type="job",
            payload={},
        )
    )
    await test_session.commit()
    test_session.add(
        PipelineEvent(
            event_id=uuid4(),
            event_type="job.discovered.v1",
            version="v1",
            correlation_id="corr-1",
            idempotency_key=key,
            entity_id="job-1",
            entity_type="job",
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()
