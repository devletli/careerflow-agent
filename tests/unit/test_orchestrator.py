import pytest
import pytest_asyncio
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from shared.db.models import Base, Job, Application
from shared.contracts.events import (
    JobDiscoveredEvent,
)
from shared.contracts.models import PipelineStatus
from services.orchestrator.app.duplicate_detector import (
    find_existing_job,
    check_submission_eligibility,
)
from services.orchestrator.app.worker import OrchestratorWorker


@pytest_asyncio.fixture
async def orchestrator_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_detector_job(orchestrator_session: AsyncSession):
    job = Job(
        id=uuid4(),
        source="workable",
        source_job_id="w-100",
        company="TechCorp",
        title="AI Engineer",
        url="https://workable.com/w-100",
        job_fingerprint="fp-w-100",
        status="NORMALIZED",
    )
    orchestrator_session.add(job)
    await orchestrator_session.commit()

    # Found by source + source_job_id
    found1 = await find_existing_job(orchestrator_session, "workable", "w-100")
    assert found1 is not None
    assert found1.id == job.id

    # Found by fingerprint
    found2 = await find_existing_job(orchestrator_session, "other", "other-id", "fp-w-100")
    assert found2 is not None
    assert found2.id == job.id

    # Not found
    not_found = await find_existing_job(orchestrator_session, "workable", "w-999", "nonexistent-fp")
    assert not_found is None


@pytest.mark.asyncio
async def test_submission_eligibility_rejections(orchestrator_session: AsyncSession):
    job = Job(
        id=uuid4(),
        source="workable",
        source_job_id="w-200",
        company="BetaCorp",
        title="DevOps Lead",
        url="https://workable.com/w-200",
        job_fingerprint="fp-w-200",
    )
    orchestrator_session.add(job)
    await orchestrator_session.commit()

    # Case 1: Unseen application fingerprint is eligible
    eligible, reason = await check_submission_eligibility(orchestrator_session, "app-fp-new")
    assert eligible is True
    assert reason is None

    # Case 2: Already SUBMITTED application is rejected
    app_submitted = Application(
        id=uuid4(),
        job_id=job.id,
        candidate_id="cand-1",
        application_fingerprint="app-fp-submitted",
        status=PipelineStatus.SUBMITTED.value,
    )
    orchestrator_session.add(app_submitted)
    await orchestrator_session.commit()

    eligible, reason = await check_submission_eligibility(orchestrator_session, "app-fp-submitted")
    assert eligible is False
    assert "already submitted or verified" in reason

    # Case 3: Prior BLOCKED application is rejected
    app_blocked = Application(
        id=uuid4(),
        job_id=job.id,
        candidate_id="cand-1",
        application_fingerprint="app-fp-blocked",
        status=PipelineStatus.BLOCKED.value,
        blocked_reason="CAPTCHA encountered",
    )
    orchestrator_session.add(app_blocked)
    await orchestrator_session.commit()

    eligible, reason = await check_submission_eligibility(orchestrator_session, "app-fp-blocked")
    assert eligible is False
    assert "Prior run was blocked" in reason


@pytest.mark.asyncio
async def test_orchestrator_handle_job_discovered():
    from contextlib import asynccontextmanager

    worker = OrchestratorWorker()
    worker.bus = AsyncMock()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_get_session():
        async with session_maker() as session:
            yield session
            await session.commit()

    with patch("services.orchestrator.app.worker.get_session", mock_get_session):
        event = JobDiscoveredEvent(
            correlation_id="c-test",
            entity_id=str(uuid4()),
            payload={
                "source": "workable",
                "source_job_id": "job-abc",
                "company": "Test Company",
                "title": "Staff AI Engineer",
                "url": "https://workable.com/job-abc",
            },
        )
        await worker.handle_event(event)

        async with session_maker() as session:
            job = await find_existing_job(session, "workable", "job-abc")
            assert job is not None
            assert job.company == "Test Company"
            assert job.status == PipelineStatus.NORMALIZED.value

    await engine.dispose()
