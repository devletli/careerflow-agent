import asyncio
import hashlib
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import FastAPI, Depends, HTTPException, Query, status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, desc
from typing import Any, Optional
import logging

from app.errors import DomainError, domain_error_handler, unhandled_handler
from app.security import ApiKey
from shared.config import settings
from shared.db.session import get_db_session, check_db_health
from shared.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationQuestion,
    Document,
    Job,
    JobMatch,
    PipelineEvent,
)
from shared.infra.rate_limit import RateLimited, check_action_limit
from shared.infra.redis_bus import RedisEventBus
from shared.infra.storage import MinIOClient
from shared.contracts.events import BaseEvent

logger = logging.getLogger("api")

app = FastAPI(
    title="AI Job Agent API",
    description="Control and monitoring REST API for AI Job Agent",
    version="0.1.0",
)

redis_bus = RedisEventBus()
minio_client = MinIOClient()

app.add_exception_handler(DomainError, domain_error_handler)
app.add_exception_handler(Exception, unhandled_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-API-Key"],
)
CONTROL_ACTIONS = {
    "discover",
    "match",
    "generate_documents",
    "analyze_applications",
    "fill_applications",
    "submit_application",
}
CONFIRMATION_REQUIRED_ACTIONS = {"fill_applications", "submit_application"}


class PipelineControlRequest(BaseModel):
    action: str
    confirmed: bool = False
    application_id: Optional[UUID] = None


@app.get("/health")
async def health() -> JSONResponse:
    """Health check validating connectivity to PostgreSQL, Redis, and MinIO."""
    db_healthy = await check_db_health()
    redis_healthy = await redis_bus.ping()
    minio_healthy = minio_client.check_health()

    overall = db_healthy and redis_healthy and minio_healthy
    status_code = 200 if overall else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if overall else "degraded",
            "dependencies": {
                "postgres": db_healthy,
                "redis": redis_healthy,
                "minio": minio_healthy,
            },
        },
    )


@app.get("/api/v1/status", dependencies=[ApiKey])
def status() -> dict[str, Any]:
    return {
        "service": "api",
        "version": "0.1.0",
        "automation_mode": settings.AUTOMATION_MODE,
        "auto_submit": settings.AUTO_SUBMIT,
        "min_match_score": settings.MIN_MATCH_SCORE,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
    }


@app.post("/api/v1/pipeline/actions", status_code=http_status.HTTP_202_ACCEPTED, dependencies=[ApiKey])
async def run_pipeline_action(
    request: PipelineControlRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Queues a targeted worker action; form filling requires explicit confirmation."""
    if request.action not in CONTROL_ACTIONS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action: {request.action}",
        )
    if request.action in CONFIRMATION_REQUIRED_ACTIONS and not request.confirmed:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Explicit confirmation is required before this browser action.",
        )
    if request.action == "submit_application" and request.application_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An application_id is required to submit an application.",
        )
    if request.action == "submit_application":
        application = await session.get(Application, request.application_id)
        if application is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Application not found.",
            )
        if application.status == "SUBMITTED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Application has already been submitted.",
            )

    try:
        await check_action_limit(request.action, await redis_bus.get_redis())
    except RateLimited as exc:
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {exc.action}; retry later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    correlation_id = f"control-{uuid4().hex[:12]}"
    event = BaseEvent(
        event_type="pipeline.control.v1",
        correlation_id=correlation_id,
        entity_id=str(request.application_id or request.action),
        payload={
            "action": request.action,
            "confirmed": request.confirmed,
            "application_id": str(request.application_id) if request.application_id else None,
        },
    )
    message_id = await redis_bus.publish(event)
    logger.info(
        "Queued pipeline action action=%s correlation_id=%s message_id=%s",
        request.action,
        correlation_id,
        message_id,
        extra={"correlation_id": correlation_id, "entity_id": event.entity_id},
    )
    return {
        "status": "queued",
        "action": request.action,
        "correlation_id": correlation_id,
        "message_id": message_id,
    }


class ApplicationExecuteRequest(BaseModel):
    action: str


APPLICATION_EXECUTE_ACTIONS = {"prepare", "submit", "retry", "continue"}
# Legacy alias: older rows use READY_TO_APPLY where the dashboard uses READY_TO_SUBMIT.
READY_STATUSES = {"READY_TO_SUBMIT", "READY_TO_APPLY"}


@app.patch(
    "/api/v1/applications/{application_id}/execute",
    dependencies=[ApiKey],
    response_model=None,
)
async def execute_application_action(
    application_id: UUID,
    request: ApplicationExecuteRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any] | JSONResponse:
    """Explicit per-application action (prepare/submit/retry/continue).

    The frontend sends the semantic action explicitly; each branch maps to a
    distinct operation instead of funneling everything into one submit call.
    """
    if request.action not in APPLICATION_EXECUTE_ACTIONS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action: {request.action}.",
        )
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    status = application.status

    if request.action == "prepare":
        if status in READY_STATUSES:
            return {"id": str(application.id), "status": application.status, "action": "prepare"}
        if status != "CREATED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Prepare is only valid from CREATED (current: {status}).",
            )
        application.status = "READY_TO_SUBMIT"
        application.blocked_reason = None
        application.failure_reason = None
        await session.flush()
        return {"id": str(application.id), "status": application.status, "action": "prepare"}

    if request.action == "submit":
        if status == "SUBMITTED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Application has already been submitted (retryable=false).",
            )
        if status in ("RUNNING", "FILLING", "SUBMITTING"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Application is already running (current: {status}).",
            )
        if status == "REQUIRES_HUMAN":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Submission result is uncertain; manual review required (retryable=false).",
            )
        if status in ("BLOCKED", "FAILED"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Resolve {status} first (use retry/continue); submit forbidden (retryable=false).",
            )
        if status not in READY_STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Submit is only valid from READY_TO_SUBMIT (current: {status}).",
            )
        # The browser only submits in FULL_AUTO + AUTO_SUBMIT. Reject here
        # with an actionable message instead of silently filling the form,
        # which would never produce SUBMITTED or REQUIRES_HUMAN.
        if settings.AUTOMATION_MODE != "FULL_AUTO" or not settings.AUTO_SUBMIT:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Submission is disabled in the current mode "
                    f"({settings.AUTOMATION_MODE}, AUTO_SUBMIT={settings.AUTO_SUBMIT}); "
                    "set AUTOMATION_MODE=FULL_AUTO and AUTO_SUBMIT=true to submit."
                ),
            )
        correlation_id = f"control-{uuid4().hex[:12]}"
        event = BaseEvent(
            event_type="pipeline.control.v1",
            correlation_id=correlation_id,
            entity_id=str(application.id),
            payload={
                "action": "submit_application",
                "confirmed": True,
                "application_id": str(application.id),
            },
        )
        message_id = await redis_bus.publish(event)
        return JSONResponse(
            status_code=http_status.HTTP_202_ACCEPTED,
            content={
                "status": "queued",
                "action": "submit",
                "application_id": str(application.id),
                "correlation_id": correlation_id,
                "message_id": message_id,
            },
        )

    if request.action == "retry":
        # Safe default: retry forbidden everywhere except a plain FAILED row.
        if status == "SUBMITTED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Already submitted; retry forbidden (retryable=false).",
            )
        if status == "REQUIRES_HUMAN":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ambiguous submission; retry forbidden, continue manually (retryable=false).",
            )
        if status in ("RUNNING", "FILLING", "SUBMITTING"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Application is running (current: {status}); retry forbidden.",
            )
        if status == "BLOCKED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Blocked (e.g. CAPTCHA/MFA/login); human intervention required (retryable=false).",
            )
        if status != "FAILED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Nothing to retry from {status} (retryable=false).",
            )
        application.status = "READY_TO_SUBMIT"
        application.failure_reason = None
        await session.flush()
        return {
            "id": str(application.id),
            "status": application.status,
            "action": "retry",
            "retryable": True,
        }

    # request.action == "continue": honest manual workflow, no fake session resume.
    if status != "REQUIRES_HUMAN":
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Continue is only valid from REQUIRES_HUMAN (current: {status}).",
        )
    job = await session.get(Job, application.job_id)
    application_url = (job.application_url or job.url) if job else None
    return {
        "id": str(application.id),
        "status": application.status,
        "action": "continue",
        "application_url": application_url,
        "manual_steps": [
            "Open the application URL in your own browser.",
            "Review the pre-filled data and documents.",
            "Submit manually only after you see the site's own confirmation.",
        ],
    }


@app.get("/api/v1/jobs", dependencies=[ApiKey])
async def list_jobs(
    limit: int = Query(default=100, le=100),
    offset: int = 0,
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


@app.get("/api/v1/applications", dependencies=[ApiKey])
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


@app.get("/api/v1/applications/{application_id}/desktop-context", dependencies=[ApiKey])
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


@app.get("/api/v1/documents", dependencies=[ApiKey])
async def list_documents(
    limit: int = Query(default=100, le=100),
    offset: int = 0,
    q: Optional[str] = Query(default=None, description="Search company/title/type"),
    type: Optional[str] = Query(default=None, description="Filter by document type (cv, cover_letter)"),
    application_id: Optional[UUID] = Query(default=None, description="Filter by linked application"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(Document, Job.company, Job.title, Application.id, Application.status)
        .join(Job, Job.id == Document.job_id)
        .outerjoin(Application, Application.id == Document.application_id)
        .order_by(desc(Document.created_at))
        .offset(offset)
        .limit(limit)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Job.company.ilike(like)) | (Job.title.ilike(like)) | (Document.type.ilike(like))
        )
    if type:
        stmt = stmt.where(Document.type == type)
    if application_id is not None:
        stmt = stmt.where(Document.application_id == application_id)
    res = await session.execute(stmt)
    rows = res.all()

    # Latest = highest version (then newest) per (job, type, language).
    newest: dict[tuple[Any, Any, Any], Document] = {}
    for document, *_ in rows:
        key = (document.job_id, document.type, document.language)
        current = newest.get(key)
        if current is None or (document.version, document.created_at) > (current.version, current.created_at):
            newest[key] = document
    latest_ids = {d.id for d in newest.values()}

    return [
        {
            "id": str(document.id),
            "job_id": str(document.job_id),
            "application": (
                {"id": str(app_id), "status": app_status}
                if app_id is not None
                else None
            ),
            "company": company,
            "job_title": job_title,
            "type": document.type,
            "language": document.language,
            "version": document.version,
            "is_latest": document.id in latest_ids,
            "mime_type": document.mime_type,
            "metadata": document.metadata_json,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "view_url": f"/api/v1/documents/{document.id}/file?download=0",
            "download_url": f"/api/v1/documents/{document.id}/file?download=1",
        }
        for document, company, job_title, app_id, app_status in rows
    ]


async def _stream_document_bytes(
    document_id: UUID, session: AsyncSession
) -> tuple[Document, bytes]:
    """Loads a private artifact from MinIO (never exposes bucket URLs)."""
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    try:
        content = await asyncio.to_thread(
            minio_client.download_bytes,
            document.minio_key,
            document.minio_bucket,
        )
    except Exception as exc:
        logger.error("Unable to download document_id=%s: %s", document_id, exc)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="Document storage is unavailable.",
        ) from exc
    return document, content


def _document_filename(document: Document) -> str:
    filename = f"{document.type}_{document.language}_v{document.version}"
    if document.mime_type == "application/pdf":
        filename += ".pdf"
    elif "wordprocessingml" in document.mime_type:
        filename += ".docx"
    return filename


@app.get("/api/v1/documents/{document_id}/file", dependencies=[ApiKey])
async def get_document_file(
    document_id: UUID,
    download: bool = Query(default=False, description="True for attachment download, False for inline view"),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Streams a private artifact; inline view or attachment download."""
    document, content = await _stream_document_bytes(document_id, session)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        BytesIO(content),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'{disposition}; filename="{_document_filename(document)}"'},
    )


@app.get("/api/v1/documents/{document_id}/download", dependencies=[ApiKey])
async def download_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Legacy attachment download (kept for compatibility; prefer /file)."""
    document, content = await _stream_document_bytes(document_id, session)
    return StreamingResponse(
        BytesIO(content),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{_document_filename(document)}"'},
    )


class DocumentLinkRequest(BaseModel):
    application_id: Optional[UUID] = None


class ApplicationNotesRequest(BaseModel):
    notes: str = ""


class ManualApplicationRequest(BaseModel):
    url: str


@app.get("/api/v1/applications/{application_id}", dependencies=[ApiKey])
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


@app.patch("/api/v1/applications/{application_id}/documents/{doc_id}", dependencies=[ApiKey])
async def link_document(
    application_id: UUID,
    doc_id: UUID,
    request: DocumentLinkRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Manually links a document to an application (or unlinks with null)."""
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    document = await session.get(Document, doc_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    target_id = request.application_id
    if target_id is not None:
        target = await session.get(Application, target_id)
        if target is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Target application not found.",
            )
        if target.job_id != document.job_id:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document and application belong to different jobs.",
            )
        document.application_id = target.id
    else:
        document.application_id = None
    return {
        "id": str(document.id),
        "application_id": str(document.application_id) if document.application_id else None,
    }


@app.patch("/api/v1/applications/{application_id}", dependencies=[ApiKey])
async def update_application_notes(
    application_id: UUID,
    request: ApplicationNotesRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Stores free-form reviewer notes inside submission_metadata (no schema change)."""
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    metadata = dict(application.submission_metadata or {})
    metadata["notes"] = request.notes
    application.submission_metadata = metadata
    return {"id": str(application.id), "notes": request.notes}


@app.post("/api/v1/applications/manual", dependencies=[ApiKey])
async def create_manual_application(
    request: ManualApplicationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Creates a Job + Application from a posting URL (idempotent by fingerprint)."""
    from urllib.parse import urlparse

    from shared.contracts.fingerprint import (
        compute_application_fingerprint,
        compute_job_fingerprint,
    )
    from shared.contracts.models import PipelineStatus

    url = (request.url or "").strip()
    if not url:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A posting URL is required.",
        )
    from shared.infra.urls import assert_public_http_url

    try:
        url = assert_public_http_url(url if "://" in url else f"https://{url}")
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rejected posting URL: {exc}",
        ) from exc
    parsed = urlparse(url)
    domain = (parsed.netloc or "").removeprefix("www.")
    if not domain:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse a domain from the URL.",
        )
    company = domain
    title = f"Manual application ({domain})"
    source_job_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
    job_fp = compute_job_fingerprint(company, title, url)

    res = await session.execute(
        select(Job).where((Job.source == "manual") & (Job.source_job_id == source_job_id))
    )
    job = res.scalars().first()
    job_created = False
    if job is None:
        job = Job(
            id=uuid4(),
            source="manual",
            source_job_id=source_job_id,
            company=company,
            title=title,
            url=url,
            application_url=url,
            job_fingerprint=job_fp,
            status=PipelineStatus.NORMALIZED.value,
        )
        session.add(job)
        job_created = True

    candidate_id = "manual"
    app_fp = compute_application_fingerprint(candidate_id, job.job_fingerprint)
    res_a = await session.execute(
        select(Application).where(Application.application_fingerprint == app_fp)
    )
    application = res_a.scalars().first()
    app_created = False
    if application is None:
        application = Application(
            id=uuid4(),
            job_id=job.id,
            candidate_id=candidate_id,
            application_fingerprint=app_fp,
            status=PipelineStatus.READY_TO_APPLY.value,
            automation_mode=settings.AUTOMATION_MODE,
        )
        session.add(application)
        app_created = True

    await session.flush()
    status_code = (
        http_status.HTTP_201_CREATED if (job_created or app_created) else http_status.HTTP_200_OK
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "created": job_created or app_created,
            "job": {"id": str(job.id), "company": job.company, "title": job.title},
            "application": {"id": str(application.id), "status": application.status},
        },
    )


@app.patch("/api/v1/documents/backfill", dependencies=[ApiKey])
async def backfill_document_application_links(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Backfill application_id for documents by matching via job_id.
    
    For each document with application_id=NULL, find applications sharing
    the same job_id and link them. If a job has multiple applications,
    the document stays unlinked to avoid ambiguity.
    """
    from sqlalchemy import select

    # Find all documents without an application link.
    doc_stmt = select(Document).where(Document.application_id.is_(None))
    doc_res = await session.execute(doc_stmt)
    documents = doc_res.scalars().all()

    # Group applications by job_id.
    app_stmt = select(Application.job_id, Application.id).distinct(Application.job_id)
    app_res = await session.execute(app_stmt)
    apps_by_job: dict[Any, list[Any]] = {}
    for job_id, app_id in app_res.all():
        apps_by_job.setdefault(job_id, []).append(app_id)

    linked = 0
    for doc in documents:
        matching_apps = apps_by_job.get(doc.job_id, [])
        if len(matching_apps) == 1:
            doc.application_id = matching_apps[0]
            linked += 1
        # If 0 or >1 matching applications, leave document unlinked.

    await session.commit()
    return {"linked": linked, "total_documents_without_app": len(documents)}


@app.get("/api/v1/events", dependencies=[ApiKey])
async def list_events(
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = select(PipelineEvent).order_by(desc(PipelineEvent.created_at)).limit(limit)
    res = await session.execute(stmt)
    events = res.scalars().all()
    return [
        {
            "event_id": str(e.event_id),
            "event_type": e.event_type,
            "correlation_id": e.correlation_id,
            "entity_id": e.entity_id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in events
    ]
