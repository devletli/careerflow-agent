"""Job listings."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.db.models import Document, Job, JobMatch
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
async def list_jobs(
    limit: int = Query(default=100, le=100),
    offset: int = 0,
    q: Optional[str] = Query(default=None, description="Search company/title/URL"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    document_count = (
        select(func.count(Document.id))
        .where(Document.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    match_score = (
        select(JobMatch.overall_score)
        .where(JobMatch.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    qualification = (
        select(JobMatch.qualification_status)
        .where(JobMatch.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    explanation = (
        select(JobMatch.explanation)
        .where(JobMatch.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    stmt = (
        select(Job, document_count, match_score, qualification, explanation)
        .order_by(desc(Job.created_at))
        .offset(offset)
        .limit(limit)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Job.company.ilike(like)) | (Job.title.ilike(like)) | (Job.url.ilike(like))
        )
    res = await session.execute(stmt)
    rows = res.all()
    return [
        {
            "id": str(j.id),
            "source": j.source,
            "source_job_id": j.source_job_id,
            "company": j.company,
            "title": j.title,
            "url": j.url,
            "location": j.location,
            "remote_status": j.remote_status,
            "status": j.status,
            "job_fingerprint": j.job_fingerprint,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "document_count": doc_count,
            "match_score": score,
            "qualification_status": qualification_status,
            "match_explanation": match_explanation,
            "has_documents": doc_count > 0,
        }
        for j, doc_count, score, qualification_status, match_explanation in rows
    ]
