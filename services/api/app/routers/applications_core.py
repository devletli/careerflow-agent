"""Applications: liste/detay (salt okunur merkez kayit gorunumleri)."""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    Document,
    Job,
    JobMatch,
    PipelineEvent,
)
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
async def list_applications(
    limit: int = Query(default=100, le=100),
    offset: int = 0,
    q: Optional[str] = Query(default=None, description="Search company/title/URL"),
    status: Optional[str] = Query(default=None, description="Filter by application status"),
    min_score: Optional[float] = Query(default=None, description="Minimum match score"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    match_score = (
        select(JobMatch.overall_score)
        .where(JobMatch.job_id == Application.job_id)
        .correlate(Application)
        .scalar_subquery()
    )
    stmt = (
        select(Application, Job.company, Job.title, Job.application_url, Job.url, match_score)
        .join(Job, Job.id == Application.job_id)
        .order_by(desc(Application.created_at))
        .offset(offset)
        .limit(limit)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Job.company.ilike(like)) | (Job.title.ilike(like)) | (Job.url.ilike(like))
        )
    if status:
        stmt = stmt.where(Application.status == status)
    if min_score is not None:
        stmt = stmt.where(match_score >= min_score)
    res = await session.execute(stmt)
    rows = res.all()

    # Document summary per application job (latest CV/cover-letter ids).
    job_ids = list({a.job_id for a, *_ in rows})
    docs_by_job: dict[Any, list[Document]] = {}
    if job_ids:
        dres = await session.execute(
            select(Document).where(Document.job_id.in_(job_ids)).order_by(desc(Document.created_at))
        )
        for d in dres.scalars().all():
            docs_by_job.setdefault(d.job_id, []).append(d)
    out = []
    for a, company, title, application_url, job_url, score in rows:
        docs = docs_by_job.get(a.job_id, [])
        latest: dict[tuple[Any, Any], Document] = {}
        for d in docs:
            key = (d.type, d.language)
            if key not in latest or (d.version, d.created_at) > (latest[key].version, latest[key].created_at):
                latest[key] = d
        out.append(
            {
                "id": str(a.id),
                "job_id": str(a.job_id),
                "company": company,
                "title": title,
                "application_url": application_url or job_url,
                "candidate_id": a.candidate_id,
                "status": a.status,
                "automation_mode": a.automation_mode,
                "attempts": a.attempts,
                "blocked_reason": a.blocked_reason,
                "failure_reason": a.failure_reason,
                "application_fingerprint": a.application_fingerprint,
                "match_score": score,
                "documents": {
                    "count": len(docs),
                    "latest": [
                        {"id": str(d.id), "type": d.type, "language": d.language}
                        for d in latest.values()
                    ],
                },
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        )
    return out


@router.get("/{application_id}/desktop-context")
async def get_desktop_application_context(
    application_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Returns verified data for the local, visible Playwright helper only."""
    stmt = (
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(Application.id == application_id)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    application, job = row

    answers_stmt = (
        select(ApplicationQuestion.question_key, ApplicationAnswer.answer_value)
        .join(
            ApplicationAnswer,
            ApplicationAnswer.question_id == ApplicationQuestion.id,
        )
        .where(
            ApplicationQuestion.application_id == application.id,
            ApplicationAnswer.is_verified.is_(True),
        )
    )
    answer_rows = await session.execute(answers_stmt)
    verified_answers = {
        question_key: answer_value.get("value")
        for question_key, answer_value in answer_rows
        if isinstance(answer_value, dict) and answer_value.get("value") is not None
    }

    documents_stmt = select(Document).where(Document.job_id == job.id)
    documents = (await session.execute(documents_stmt)).scalars().all()
    document_paths = {
        "resume": next(
            (
                document.metadata_json.get("artifact_relative_path")
                for document in documents
                if document.type == "cv" and document.version == 1
            ),
            None,
        ),
        "cover_letter": next(
            (
                document.metadata_json.get("artifact_relative_path")
                for document in documents
                if document.type == "cover_letter"
            ),
            None,
        ),
    }

    return {
        "application_id": str(application.id),
        "company": job.company,
        "title": job.title,
        "application_url": job.application_url or job.url,
        "verified_answers": verified_answers,
        "document_paths": document_paths,
    }


@router.get("/{application_id}")
async def get_application_detail(
    application_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Central application record: job, score, documents, form analysis, events."""
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    job = await session.get(Job, application.job_id)
    match = (
        await session.execute(select(JobMatch).where(JobMatch.job_id == application.job_id))
    ).scalars().first()
    docs = (
        await session.execute(
            select(Document)
            .where(Document.job_id == application.job_id)
            .order_by(desc(Document.version), desc(Document.created_at))
        )
    ).scalars().all()
    newest: dict[tuple[Any, Any], Any] = {}
    for d in docs:
        key = (d.type, d.language)
        if key not in newest:
            newest[key] = d.id
    questions = (
        await session.execute(
            select(ApplicationQuestion).where(ApplicationQuestion.application_id == application.id)
        )
    ).scalars().all()
    answers = (
        await session.execute(
            select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id)
        )
    ).scalars().all()
    answer_by_q = {a.question_id: a for a in answers}
    events = (
        await session.execute(
            select(PipelineEvent)
            .where(PipelineEvent.entity_id.in_([str(application.id), str(application.job_id)]))
            .order_by(desc(PipelineEvent.created_at))
            .limit(50)
        )
    ).scalars().all()
    return {
        "id": str(application.id),
        "job_id": str(application.job_id),
        "company": job.company if job else None,
        "title": job.title if job else None,
        "job": (
            {
                "id": str(job.id),
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "application_url": job.application_url,
                "location": job.location,
                "remote_status": job.remote_status,
                "status": job.status,
            }
            if job
            else None
        ),
        "status": application.status,
        "automation_mode": application.automation_mode,
        "attempts": application.attempts,
        "blocked_reason": application.blocked_reason,
        "failure_reason": application.failure_reason,
        "application_url": (job.application_url or job.url) if job else None,
        "notes": (application.submission_metadata or {}).get("notes", ""),
        "match": (
            {
                "overall_score": match.overall_score,
                "qualification_status": match.qualification_status,
                "explanation": match.explanation,
                "matching_skills": match.matching_skills,
                "missing_skills": match.missing_skills,
            }
            if match
            else None
        ),
        "documents": [
            {
                "id": str(d.id),
                "type": d.type,
                "language": d.language,
                "version": d.version,
                "is_latest": newest.get((d.type, d.language)) == d.id,
                "linked": d.application_id == application.id,
                "mime_type": d.mime_type,
                "view_url": f"/api/v1/documents/{d.id}/file?download=0",
                "download_url": f"/api/v1/documents/{d.id}/file?download=1",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "questions": [
            {
                "id": str(q.id),
                "key": q.question_key,
                "text": q.question_text,
                "type": q.question_type,
                "is_required": q.is_required,
                "classification": q.classification,
                "answer": (
                    {
                        "value": (answer_by_q[q.id].answer_value or {}).get("value"),
                        "source": answer_by_q[q.id].answer_source,
                        "is_verified": answer_by_q[q.id].is_verified,
                    }
                    if q.id in answer_by_q
                    else None
                ),
            }
            for q in questions
        ],
        "events": [
            {
                "event_id": str(e.event_id),
                "event_type": e.event_type,
                "correlation_id": e.correlation_id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in events
        ],
        "created_at": application.created_at.isoformat() if application.created_at else None,
    }
