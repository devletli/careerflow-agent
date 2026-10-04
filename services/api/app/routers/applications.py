"""Applications: central record (execute, list, detail, link, notes, manual)."""
import hashlib
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.confirmations import consume_confirmation_token
from app.deps import redis_bus
from app.security import require_api_key
from shared.config import settings
from shared.contracts.events import BaseEvent
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

APPLICATION_EXECUTE_ACTIONS = {"prepare", "submit", "retry", "continue"}
# Legacy alias: older rows use READY_TO_APPLY where the dashboard uses READY_TO_SUBMIT.
READY_STATUSES = {"READY_TO_SUBMIT", "READY_TO_APPLY"}


class ApplicationExecuteRequest(BaseModel):
    action: str
    # Faz 3B: submit icin tek kullanimlik sunucu tokeni (UI onayina guvenilmez).
    confirmation_token: Optional[str] = None


class DocumentLinkRequest(BaseModel):
    application_id: Optional[UUID] = None


class ApplicationNotesRequest(BaseModel):
    notes: str = ""


class ManualApplicationRequest(BaseModel):
    url: str


@router.patch(
    "/{application_id}/execute",
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
        # Faz 3B: UI onayina guvenme; tek kullanimlik sunucu tokeni sart (B2: Redis GETDEL).
        if not await consume_confirmation_token(
            await redis_bus.get_redis(), request.confirmation_token, "submit", str(application_id)
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "A single-use confirmation token is required before submission. "
                    "Mint one via POST /api/v1/confirmations right after the user confirms."
                ),
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


@router.patch("/{application_id}/documents/{doc_id}")
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


@router.patch("/{application_id}")
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


@router.post("/manual")
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
