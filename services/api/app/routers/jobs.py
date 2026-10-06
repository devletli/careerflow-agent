"""Job listings."""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import logger, minio_client
from app.security import require_api_key
from shared.db.models import Application, Document, Job, JobMatch
from shared.db.session import get_db_session

JOB_USER_STATUSES = frozenset({"NEW", "INTERESTED", "SHORTLISTED", "IGNORED", "ARCHIVED"})


class JobUpdateRequest(BaseModel):
    user_status: Optional[str] = None

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
    user_status: Optional[str] = Query(default=None, description="Filter by human board state"),
    exclude_archived: bool = Query(default=False, description="Hide ARCHIVED jobs"),
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
    if user_status:
        stmt = stmt.where(Job.user_status == user_status.upper())
    if exclude_archived:
        stmt = stmt.where((Job.user_status.is_(None)) | (Job.user_status != "ARCHIVED"))
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
            "user_status": j.user_status,
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


_RUNNING_APPLICATION_STATUSES = frozenset({"RUNNING", "FILLING", "SUBMITTING"})


@router.patch("/{job_id}")
async def update_job(
    job_id: UUID,
    request: JobUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Updates the human board state without touching pipeline `status`."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )
    if "user_status" in request.model_fields_set:
        if request.user_status is None:
            job.user_status = None
        else:
            user_status = request.user_status.upper()
            if user_status not in JOB_USER_STATUSES:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown user_status: {request.user_status}.",
                )
            job.user_status = user_status
        await session.flush()
    return {"id": str(job.id), "user_status": job.user_status, "status": job.status}


@router.delete("/{job_id}")
async def delete_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Deletes a job and its dependent rows (single transaction boundary).

    ORM cascades (models.py) remove requirements, matches, documents and
    applications (+ their questions/answers). AutomationRun rows use
    SET NULL and are preserved as audit trail; PipelineEvent rows are
    keyed by string entity_id and are likewise preserved. MinIO artifacts
    belonging only to this job are removed after the DB delete.
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )
    running = (
        await session.execute(
            select(func.count(Application.id)).where(
                Application.job_id == job.id,
                Application.status.in_(_RUNNING_APPLICATION_STATUSES),
            )
        )
    ).scalar() or 0
    if running:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Job has a running application; deletion is blocked while automation is active.",
        )
    docs = (
        await session.execute(select(Document).where(Document.job_id == job.id))
    ).scalars().all()
    # Only clean up objects no other document still references.
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for d in docs:
        pair = (d.minio_bucket, d.minio_key)
        if pair not in seen:
            seen.add(pair)
            keys.append(pair)
    await session.delete(job)
    await session.flush()
    # MinIO cleanup is best-effort AFTER the authoritative DB delete.
    # Failures are logged (never silent) but do not resurrect the DB row;
    # orphaned objects can be garbage-collected later.
    for bucket, key in keys:
        still_referenced = (
            await session.execute(
                select(func.count(Document.id)).where(
                    Document.minio_bucket == bucket,
                    Document.minio_key == key,
                )
            )
        ).scalar() or 0
        if still_referenced:
            continue
        try:
            ok = await _remove_minio_object(key, bucket)
        except Exception:  # noqa: BLE001 - logged inside helper
            ok = False
        if not ok:
            logger.error("MinIO cleanup failed for deleted job_id=%s", job_id)
    return {"id": str(job_id), "deleted": True}


async def _remove_minio_object(key: str, bucket: str) -> bool:
    """Runs the blocking MinIO delete off the event loop."""
    import asyncio

    return await asyncio.to_thread(minio_client.delete_object, key, bucket)
