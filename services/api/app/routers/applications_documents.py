"""Applications: lifecycle, document snapshots, notes, manual intake."""
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.config import settings
from shared.db.models import (
    Application,
    ApplicationDocument,
    ApplicationStatusHistory,
    Document,
    Job,
)
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_api_key)],
)

LIFECYCLE_STATUSES = frozenset(
    {"DRAFT", "PREPARED", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"}
)
APPLICATION_METHODS = frozenset({"MANUAL", "AUTOMATED"})
DOCUMENT_ROLES = frozenset({"CV", "COVER_LETTER", "OTHER"})
HISTORY_SOURCES = frozenset({"MANUAL", "AUTOMATED", "SYSTEM"})


def _default_role(doc_type: str) -> str:
    if doc_type == "cover_letter":
        return "COVER_LETTER"
    if doc_type == "cv":
        return "CV"
    return "OTHER"


def _parse_dt(value: Any, field: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid {field}: expected ISO datetime.",
            ) from exc
    else:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field}: expected ISO datetime.",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _change_lifecycle(
    session: AsyncSession,
    application: Application,
    to_status: str,
    source: str = "MANUAL",
    note: Optional[str] = None,
) -> None:
    if to_status not in LIFECYCLE_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown lifecycle_status: {to_status}.",
        )
    if source not in HISTORY_SOURCES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown source: {source}.",
        )
    from_status = application.lifecycle_status
    if from_status == to_status:
        return
    application.lifecycle_status = to_status
    if to_status == "APPLIED" and application.applied_at is None:
        application.applied_at = datetime.now(timezone.utc)
    session.add(
        ApplicationStatusHistory(
            id=uuid4(),
            application_id=application.id,
            from_status=from_status,
            to_status=to_status,
            source=source,
            note=note,
        )
    )


async def _attach_document(
    session: AsyncSession,
    application: Application,
    document: Document,
    role: Optional[str] = None,
    attached_by: str = "MANUAL",
) -> ApplicationDocument:
    role = (role or _default_role(document.type)).upper()
    if role not in DOCUMENT_ROLES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown role: {role}.",
        )
    attached_by = (attached_by or "MANUAL").upper()
    if attached_by not in HISTORY_SOURCES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown attached_by: {attached_by}.",
        )
    if document.job_id != application.job_id:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document and application belong to different jobs.",
        )
    existing = (
        await session.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == application.id,
                ApplicationDocument.document_id == document.id,
            )
        )
    ).scalars().first()
    if existing is not None:
        existing.role = role
        existing.attached_by = attached_by
        link = existing
    else:
        link = ApplicationDocument(
            id=uuid4(),
            application_id=application.id,
            document_id=document.id,
            role=role,
            attached_by=attached_by,
        )
        session.add(link)
    # Backward compat: legacy single-pointer column keeps last link.
    document.application_id = application.id
    await session.flush()
    return link


class DocumentLinkRequest(BaseModel):
    application_id: Optional[UUID] = None


class ApplicationUpdateRequest(BaseModel):
    notes: Optional[str] = None
    lifecycle_status: Optional[str] = None
    lifecycle_source: Optional[str] = None
    lifecycle_note: Optional[str] = None
    application_method: Optional[str] = None
    applied_at: Optional[str] = None
    next_action: Optional[str] = None
    next_action_due_at: Optional[str] = None


class DocumentAttachRequest(BaseModel):
    document_id: UUID
    role: Optional[str] = None
    attached_by: Optional[str] = "MANUAL"


class ManualApplicationRequest(BaseModel):
    url: str


@router.post("/{application_id}/documents")
async def attach_document(
    application_id: UUID,
    request: DocumentAttachRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Attaches an exact document version to an application (snapshot).

    The same document may be attached to many applications; each
    application keeps its own (application_id, document_id, role) row.
    """
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    document = await session.get(Document, request.document_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    link = await _attach_document(
        session, application, document, request.role, request.attached_by or "MANUAL"
    )
    return {
        "application_id": str(application.id),
        "document_id": str(document.id),
        "role": link.role,
        "attached_at": link.attached_at.isoformat() if link.attached_at else None,
    }


@router.delete("/{application_id}/documents/{document_id}")
async def detach_document(
    application_id: UUID,
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Removes one application_documents snapshot row (history-safe)."""
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    link = (
        await session.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == application.id,
                ApplicationDocument.document_id == document_id,
            )
        )
    ).scalars().first()
    if link is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document is not attached to this application.",
        )
    await session.delete(link)
    await session.flush()
    # Legacy column: clear only when no snapshot row still claims the doc.
    remaining = (
        await session.execute(
            select(ApplicationDocument).where(ApplicationDocument.document_id == document_id)
        )
    ).scalars().first()
    if remaining is None:
        document = await session.get(Document, document_id)
        if document is not None and document.application_id == application.id:
            document.application_id = None
    return {"application_id": str(application_id), "document_id": str(document_id), "detached": True}


@router.patch("/{application_id}/documents/{doc_id}")
async def link_document(
    application_id: UUID,
    doc_id: UUID,
    request: DocumentLinkRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Legacy link toggle; now backed by the application_documents snapshot.

    Linking inserts a snapshot row (sharable across applications) instead of
    moving the single documents.application_id pointer. The legacy column
    is still updated for backward compatibility.
    """
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
        link = await _attach_document(session, target, document)
        return {
            "id": str(document.id),
            "application_id": str(target.id),
            "role": link.role,
        }
    link = (
        await session.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == application.id,
                ApplicationDocument.document_id == document.id,
            )
        )
    ).scalars().first()
    if link is not None:
        await session.delete(link)
        await session.flush()
    if document.application_id == application.id:
        still = (
            await session.execute(
                select(ApplicationDocument).where(ApplicationDocument.document_id == document.id)
            )
        ).scalars().first()
        if still is None:
            document.application_id = None
    return {
        "id": str(document.id),
        "application_id": None,
    }


@router.patch("/{application_id}")
async def update_application(
    application_id: UUID,
    request: ApplicationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Updates notes, lifecycle, method, applied_at and next action.

    Lifecycle changes are recorded in application_status_history; moving to
    APPLIED stamps applied_at when unset.
    """
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    if "notes" in request.model_fields_set:
        metadata = dict(application.submission_metadata or {})
        metadata["notes"] = request.notes or ""
        application.submission_metadata = metadata
    if request.application_method is not None:
        method = request.application_method.upper()
        if method not in APPLICATION_METHODS:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown application_method: {request.application_method}.",
            )
        application.application_method = method
    if request.lifecycle_status is not None:
        await _change_lifecycle(
            session,
            application,
            request.lifecycle_status.upper(),
            (request.lifecycle_source or "MANUAL").upper(),
            request.lifecycle_note,
        )
    if "applied_at" in request.model_fields_set:
        application.applied_at = _parse_dt(request.applied_at, "applied_at")
    if "next_action" in request.model_fields_set:
        application.next_action = request.next_action or None
    if "next_action_due_at" in request.model_fields_set:
        application.next_action_due_at = _parse_dt(request.next_action_due_at, "next_action_due_at")
    await session.flush()
    return {
        "id": str(application.id),
        "lifecycle_status": application.lifecycle_status,
        "application_method": application.application_method,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "next_action": application.next_action,
        "next_action_due_at": (
            application.next_action_due_at.isoformat() if application.next_action_due_at else None
        ),
        "notes": (application.submission_metadata or {}).get("notes", ""),
    }


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
            lifecycle_status="DRAFT",
            application_method="MANUAL",
        )
        session.add(application)
        app_created = True
        session.add(
            ApplicationStatusHistory(
                id=uuid4(),
                application_id=application.id,
                from_status=None,
                to_status="DRAFT",
                source="MANUAL",
                note="Manual application created.",
            )
        )

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
