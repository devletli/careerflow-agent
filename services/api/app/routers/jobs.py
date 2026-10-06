"""Job listings: score-ranked, keyset-paginated (Faz 4)."""
import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import logger, minio_client
from app.security import require_api_key
from shared.config import settings
from shared.db.models import Application, Document, Job, JobMatch
from shared.db.session import get_db_session

JOB_USER_STATUSES = frozenset({"NEW", "INTERESTED", "SHORTLISTED", "IGNORED", "ARCHIVED"})
MATCH_BANDS = frozenset({"QUALIFIED", "REVIEW", "NOT_QUALIFIED"})


class JobUpdateRequest(BaseModel):
    user_status: Optional[str] = None


router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)


def _encode_cursor(score: float, job_id: UUID) -> str:
    raw = f"{score}|{job_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[float, UUID]:
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
        score_text, job_text = text.split("|", 1)
        return float(score_text), UUID(job_text)
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid cursor.",
        ) from exc


def _serialize_job(
    j: Job, doc_count: int, score: Optional[float],
    qualification_status: Optional[str], match_explanation: Optional[str],
) -> dict[str, Any]:
    return {
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
        "last_seen_at": j.last_seen_at.isoformat() if getattr(j, "last_seen_at", None) else None,
        "document_count": doc_count,
        "match_score": score,
        "qualification_status": qualification_status,
        "match_explanation": match_explanation,
        "has_documents": doc_count > 0,
    }


@router.get("")
async def list_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    cursor: Optional[str] = Query(default=None, description="Keyset cursor (score|job_id), base64"),
    min_score: Optional[float] = Query(default=None, description="Minimum match score"),
    band: Optional[str] = Query(default=None, description="QUALIFIED | REVIEW | NOT_QUALIFIED"),
    source: Optional[str] = Query(default=None, description="Filter by job source"),
    recent_days: Optional[int] = Query(default=None, ge=1, description="Only jobs seen in the last N days"),
    include_stale: bool = Query(default=False, description="Include STALE jobs (default hidden)"),
    sort: str = Query(default="score", description="Only 'score' is supported"),
    q: Optional[str] = Query(default=None, description="Search company/title/URL"),
    user_status: Optional[str] = Query(default=None, description="Filter by human board state"),
    exclude_archived: bool = Query(default=False, description="Hide ARCHIVED jobs"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Score-ranked jobs, keyset-paginated.

    Default order: match score DESC (unscored last), tie-break job id.
    Response: {"items", "next_cursor", "total", "scored", "unscored"}.
    STALE jobs are hidden unless include_stale=true (history preserved).
    """
    if sort != "score":
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only sort=score is supported.",
        )
    if band is not None and band.upper() not in MATCH_BANDS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown band: {band}.",
        )
    document_count = (
        select(func.count(Document.id))
        .where(Document.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    stmt = (
        select(Job, document_count, JobMatch.overall_score, JobMatch.qualification_status, JobMatch.explanation)
        .outerjoin(JobMatch, JobMatch.job_id == Job.id)
    )
    count_stmt = select(func.count(Job.id)).outerjoin(JobMatch, JobMatch.job_id == Job.id)
    scored_stmt = (
        select(func.count(Job.id))
        .outerjoin(JobMatch, JobMatch.job_id == Job.id)
        .where(JobMatch.overall_score.is_not(None))
    )

    def _apply_filters(s, for_counts: bool = False):
        if not include_stale:
            s = s.where(Job.status != "STALE")
        if min_score is not None:
            s = s.where(JobMatch.overall_score >= min_score)
        if band is not None:
            s = s.where(JobMatch.qualification_status == band.upper())
        if source:
            s = s.where(Job.source == source)
        if recent_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
            s = s.where(Job.created_at >= cutoff)
        if q:
            like = f"%{q}%"
            s = s.where(
                (Job.company.ilike(like)) | (Job.title.ilike(like)) | (Job.url.ilike(like))
            )
        if user_status:
            s = s.where(Job.user_status == user_status.upper())
        if exclude_archived:
            s = s.where((Job.user_status.is_(None)) | (Job.user_status != "ARCHIVED"))
        return s

    stmt = _apply_filters(stmt)
    count_stmt = _apply_filters(count_stmt)
    scored_stmt = _apply_filters(scored_stmt)

    score_col = func.coalesce(JobMatch.overall_score, -1)
    if cursor:
        cursor_score, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                score_col < cursor_score,
                and_(score_col == cursor_score, Job.id > cursor_id),
            )
        )
    stmt = stmt.order_by(score_col.desc(), Job.id).limit(limit + 1)
    res = await session.execute(stmt)
    rows = res.all()
    page, has_more = rows[:limit], len(rows) > limit
    items = [_serialize_job(j, doc_count, score, qual, expl) for j, doc_count, score, qual, expl in page]
    if has_more and page:
        last_score = page[-1][2] if page[-1][2] is not None else -1
        next_cursor: Optional[str] = _encode_cursor(float(last_score), page[-1][0].id)
    else:
        next_cursor = None
    total = (await session.execute(count_stmt)).scalar() or 0
    scored = (await session.execute(scored_stmt)).scalar() or 0
    return {
        "items": items,
        "next_cursor": next_cursor,
        "total": total,
        "scored": scored,
        "unscored": total - scored,
        "page_size": settings.JOBS_PAGE_SIZE,
    }


@router.post("/{job_id}/explain")
async def explain_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """On-demand LLM explanation for one match (Faz 3.3/5).

    Score never changes; NOT_QUALIFIED and already explained rows return the
    stored text without spending the single-unit budget.
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found.")
    match = (
        await session.execute(select(JobMatch).where(JobMatch.job_id == job.id))
    ).scalars().first()
    if match is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job has no match yet.")
    if match.qualification_status == "NOT_QUALIFIED":
        return {"id": str(job.id), "match_score": match.overall_score, "explanation": match.explanation}
    if match.explanation and not match.explanation.startswith("Overall Match Score:"):
        return {"id": str(job.id), "match_score": match.overall_score, "explanation": match.explanation}
    try:
        from services.job_matching.app.matcher import JobMatchingEngine, RunBudget
        from shared.contracts.models import JobMatchResult, QualificationStatus
        from shared.profile.loader import load_canonical_profile
    except Exception as exc:
        raise HTTPException(status_code=http_status.HTTP_502_BAD_GATEWAY, detail="Explainer unavailable.") from exc
    profile = load_canonical_profile()
    result = JobMatchResult(
        job_id=job.id,
        overall_score=match.overall_score,
        confidence=match.confidence,
        qualification=QualificationStatus(match.qualification_status),
        component_scores=match.component_scores or {},
        hard_requirements=match.hard_requirements or [],
        matching_skills=match.matching_skills or [],
        missing_skills=match.missing_skills or [],
        risks=[],
        explanation=match.explanation or "",
    )
    engine = JobMatchingEngine()
    applied = await engine.explain_if_needed(
        result=result,
        title=job.title,
        description=job.description or "",
        profile=profile,
        budget=RunBudget(1),
    )
    if applied:
        match.explanation = result.explanation
        await session.flush()
    return {"id": str(job.id), "match_score": match.overall_score, "explanation": match.explanation}


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
