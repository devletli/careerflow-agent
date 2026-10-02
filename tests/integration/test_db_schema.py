import pytest
import pytest_asyncio
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


@pytest.mark.asyncio
async def test_pipeline_event_creation(test_session: AsyncSession):
    event_id = uuid4()
    ev = PipelineEvent(
        event_id=event_id,
        event_type="job.discovered.v1",
        version="v1",
        correlation_id="corr-1",
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
        entity_id="job-2",
        entity_type="job",
        payload={"company": "Test 2"},
    )
    test_session.add(ev_dup)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()
