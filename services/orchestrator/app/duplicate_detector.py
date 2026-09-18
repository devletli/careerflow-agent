from typing import Optional, Tuple
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Job, Application
from shared.contracts.models import PipelineStatus


async def find_existing_job(
    session: AsyncSession,
    source: str,
    source_job_id: str,
    job_fingerprint: Optional[str] = None,
) -> Optional[Job]:
    """
    Checks whether a job already exists by (source, source_job_id) or by job_fingerprint.
    """
    conditions = [
        (Job.source == source) & (Job.source_job_id == source_job_id)
    ]
    if job_fingerprint:
        conditions.append(Job.job_fingerprint == job_fingerprint)

    stmt = select(Job).where(or_(*conditions))
    result = await session.execute(stmt)
    return result.scalars().first()


async def find_existing_application(
    session: AsyncSession,
    application_fingerprint: str,
) -> Optional[Application]:
    """
    Checks whether an application record already exists for this candidate + job fingerprint.
    """
    stmt = select(Application).where(
        Application.application_fingerprint == application_fingerprint
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def check_submission_eligibility(
    session: AsyncSession,
    application_fingerprint: str,
) -> Tuple[bool, Optional[str]]:
    """
    Evaluates whether an application can enter submission:
    - Reject if prior application has been SUBMITTED or VERIFIED.
    - Reject if prior application exists with status BLOCKED or DUPLICATE.
    """
    existing_app = await find_existing_application(session, application_fingerprint)
    if existing_app is None:
        return True, None

    if existing_app.status in {PipelineStatus.SUBMITTED.value, PipelineStatus.VERIFIED.value}:
        return False, f"Duplicate rejected: Application already submitted or verified (status={existing_app.status})"

    if existing_app.status == PipelineStatus.DUPLICATE.value:
        return False, "Duplicate rejected: Marked as duplicate"

    if existing_app.status == PipelineStatus.BLOCKED.value:
        return False, f"Submission blocked: Prior run was blocked ({existing_app.blocked_reason})"

    return True, None
