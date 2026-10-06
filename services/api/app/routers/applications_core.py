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
    ApplicationDocument,
    ApplicationQuestion,
    ApplicationStatusHistory,
    Document,
    Interview,
    Job,
    JobMatch,
    PipelineEvent,
)
from shared.db.session import get_db_session


async def _attached_docs_map(
    session: AsyncSession, app_ids: list[Any]
) -> dict[Any, list[tuple[ApplicationDocument, Document]]]:
    """Authoritative per-application snapshot: application_documents -> Document."""
    out: dict[Any, list[tuple[ApplicationDocument, Document]]] = {a: [] for a in app_ids}
    if not app_ids:
        return out
    rows = (
        await session.execute(
            select(ApplicationDocument, Document)
            .join(Document, Document.id == ApplicationDocument.document_id)
            .where(ApplicationDocument.application_id.in_(app_ids))
            .order_by(ApplicationDocument.attached_at)
        )
    ).all()
    for link, doc in rows:
        out.setdefault(link.application_id, []).append((link, doc))
    return out


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None

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
    lifecycle_status: Optional[str] = Query(default=None, description="Filter by lifecycle status"),
    overdue: Optional[bool] = Query(default=None, description="Only rows with next_action_due_at in the past"),
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
    if lifecycle_status:
        stmt = stmt.where(Application.lifecycle_status == lifecycle_status.upper())
    if overdue is True:
        from datetime import datetime, timezone

        stmt = stmt.where(
            Application.next_action_due_at.is_not(None),
            Application.next_action_due_at < datetime.now(timezone.utc),
        )
    if min_score is not None:
        stmt = stmt.where(match_score >= min_score)
    res = await session.execute(stmt)
    rows = res.all()

    # Document summary: authoritative per-application snapshot
    # (application_documents) + job-level latest for reference.
    job_ids = list({a.job_id for a, *_ in rows})
    docs_by_job: dict[Any, list[Document]] = {}
    if job_ids:
        dres = await session.execute(
            select(Document).where(Document.job_id.in_(job_ids)).order_by(desc(Document.created_at))
        )
        for d in dres.scalars().all():
            docs_by_job.setdefault(d.job_id, []).append(d)
    attached_map = await _attached_docs_map(session, [a.id for a, *_ in rows])
    out = []
    for a, company, title, application_url, job_url, score in rows:
        docs = docs_by_job.get(a.job_id, [])
        latest: dict[tuple[Any, Any], Document] = {}
        for d in docs:
            key = (d.type, d.language)
            if key not in latest or (d.version, d.created_at) > (latest[key].version, latest[key].created_at):
                latest[key] = d
        attached = attached_map.get(a.id, [])
        out.append(
            {
                "id": str(a.id),
                "job_id": str(a.job_id),
                "company": company,
                "title": title,
                "application_url": application_url or job_url,
                "candidate_id": a.candidate_id,
                "status": a.status,
                "lifecycle_status": a.lifecycle_status,
                "application_method": a.application_method,
                "applied_at": _iso(a.applied_at),
                "next_action": a.next_action,
                "next_action_due_at": _iso(a.next_action_due_at),
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
                    "attached": [
                        {
                            "id": str(d.id),
                            "type": d.type,
                            "language": d.language,
                            "version": d.version,
                            "role": link.role,
                            "attached_at": _iso(link.attached_at),
                        }
                        for link, d in attached
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
    history = (
        await session.execute(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application.id)
            .order_by(ApplicationStatusHistory.created_at)
        )
    ).scalars().all()
    attached_map = await _attached_docs_map(session, [application.id])
    attached = attached_map.get(application.id, [])
    attached_ids = {d.id for _, d in attached}
    # Timeline: created + doc attachments + lifecycle changes + pipeline events.
    timeline: list[dict[str, Any]] = [
        {
            "kind": "created",
            "label": "Application created",
            "timestamp": _iso(application.created_at),
        }
    ]
    for link, d in attached:
        timeline.append(
            {
                "kind": "document_attached",
                "label": f"{link.role} attached: {d.type} v{d.version} ({d.language})",
                "document_id": str(d.id),
                "role": link.role,
                "timestamp": _iso(link.attached_at),
            }
        )
    for h in history:
        timeline.append(
            {
                "kind": "status_change",
                "label": f"Status → {h.to_status}",
                "from_status": h.from_status,
                "to_status": h.to_status,
                "source": h.source,
                "note": h.note,
                "timestamp": _iso(h.created_at),
            }
        )
    interviews = (
        await session.execute(
            select(Interview)
            .where(Interview.application_id == application.id)
            .order_by(Interview.scheduled_at.asc().nulls_last())
        )
    ).scalars().all()
    for iv in interviews:
        when = _iso(iv.scheduled_at) or "unscheduled"
        timeline.append(
            {
                "kind": "interview",
                "label": f"Interview: {iv.round or 'round'} ({when})",
                "interview_id": str(iv.id),
                "round": iv.round,
                "mode": iv.mode,
                "interviewer": iv.interviewer,
                "result": iv.result,
                "timestamp": _iso(iv.scheduled_at or iv.created_at),
            }
        )
    for e in events:
        timeline.append(
            {
                "kind": "pipeline_event",
                "label": e.event_type,
                "event_id": str(e.event_id),
                "correlation_id": e.correlation_id,
                "timestamp": _iso(e.timestamp),
            }
        )
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
                "user_status": job.user_status,
            }
            if job
            else None
        ),
        "status": application.status,
        "lifecycle_status": application.lifecycle_status,
        "application_method": application.application_method,
        "applied_at": _iso(application.applied_at),
        "next_action": application.next_action,
        "next_action_due_at": _iso(application.next_action_due_at),
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
                # Authoritative link = application_documents; legacy
                # documents.application_id column is only a fallback.
                "linked": d.id in attached_ids or d.application_id == application.id,
                "attached_role": next(
                    (link.role for link, ad in attached if ad.id == d.id), None
                ),
                "mime_type": d.mime_type,
                "view_url": f"/api/v1/documents/{d.id}/file?download=0",
                "download_url": f"/api/v1/documents/{d.id}/file?download=1",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "attached_documents": [
            {
                "id": str(d.id),
                "type": d.type,
                "language": d.language,
                "version": d.version,
                "role": link.role,
                "attached_at": _iso(link.attached_at),
                "attached_by": link.attached_by,
                "mime_type": d.mime_type,
                "view_url": f"/api/v1/documents/{d.id}/file?download=0",
                "download_url": f"/api/v1/documents/{d.id}/file?download=1",
            }
            for link, d in attached
        ],
        "status_history": [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "source": h.source,
                "note": h.note,
                "created_at": _iso(h.created_at),
            }
            for h in history
        ],
        "interviews": [
            {
                "id": str(iv.id),
                "scheduled_at": _iso(iv.scheduled_at),
                "round": iv.round,
                "mode": iv.mode,
                "interviewer": iv.interviewer,
                "location": iv.location,
                "notes": iv.notes,
                "result": iv.result,
            }
            for iv in interviews
        ],
        "timeline": timeline,
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


_RUNNING_STATUSES = frozenset({"RUNNING", "FILLING", "SUBMITTING"})


@router.delete("/{application_id}")
async def delete_application(
    application_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Deletes one application without touching its job.

    Questions/answers cascade via ORM relationships. Linked documents are
    unlinked (application_id -> NULL) so job-level artifacts survive.
    AutomationRun rows use SET NULL and are preserved as audit trail.
    No business events are published for deletions.
    """
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    if application.status in _RUNNING_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Application is {application.status}; deletion is blocked while automation is active.",
        )
    # Unlink job-level documents instead of deleting another entity's data.
    linked = (
        await session.execute(
            select(Document).where(Document.application_id == application.id)
        )
    ).scalars().all()
    for doc in linked:
        doc.application_id = None
    await session.delete(application)
    await session.flush()
    return {"id": str(application_id), "deleted": True}
