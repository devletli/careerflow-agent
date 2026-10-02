import asyncio
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import FastAPI, Depends, HTTPException, Query, status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, desc
from typing import Optional
import logging

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
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
async def health():
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
def status():
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
):
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


@app.get("/api/v1/jobs", dependencies=[ApiKey])
async def list_jobs(
    limit: int = Query(default=100, le=100),
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
):
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
    session: AsyncSession = Depends(get_db_session),
):
    stmt = (
        select(Application, Job.company, Job.title, Job.application_url, Job.url)
        .join(Job, Job.id == Application.job_id)
        .order_by(desc(Application.created_at))
        .offset(offset)
        .limit(limit)
    )
    res = await session.execute(stmt)
    rows = res.all()
    return [
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
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a, company, title, application_url, job_url in rows
    ]


@app.get("/api/v1/applications/{application_id}/desktop-context", dependencies=[ApiKey])
async def get_desktop_application_context(
    application_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
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
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(Document).order_by(desc(Document.created_at)).limit(limit)
    res = await session.execute(stmt)
    documents = res.scalars().all()
    return [
        {
            "id": str(document.id),
            "job_id": str(document.job_id),
            "type": document.type,
            "language": document.language,
            "version": document.version,
            "mime_type": document.mime_type,
            "metadata": document.metadata_json,
            "artifact_relative_path": document.metadata_json.get("artifact_relative_path"),
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "download_url": f"/api/v1/documents/{document.id}/download",
        }
        for document in documents
    ]


@app.get("/api/v1/documents/{document_id}/download", dependencies=[ApiKey])
async def download_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Streams a private artifact through the API without exposing MinIO credentials."""
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

    filename = f"{document.type}_{document.language}_v{document.version}"
    if document.mime_type == "application/pdf":
        filename += ".pdf"
    elif "wordprocessingml" in document.mime_type:
        filename += ".docx"
    return StreamingResponse(
        BytesIO(content),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/events", dependencies=[ApiKey])
async def list_events(
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_db_session),
):
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
