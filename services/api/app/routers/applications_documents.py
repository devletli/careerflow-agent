"""Applications: document linking, notes, manual intake."""
import hashlib
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.config import settings
from shared.db.models import Application, Document, Job
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_api_key)],
)

class DocumentLinkRequest(BaseModel):
    application_id: Optional[UUID] = None


class ApplicationNotesRequest(BaseModel):
    notes: str = ""


class ManualApplicationRequest(BaseModel):
    url: str


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
