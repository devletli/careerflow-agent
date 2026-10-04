"""Documents: list, private file streaming, legacy download, backfill."""
import asyncio
from io import BytesIO
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import logger, minio_client
from app.security import require_api_key
from shared.db.models import Application, Document, Job
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/documents",
    tags=["documents"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
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


@router.get("/{document_id}/file")
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


@router.get("/{document_id}/download")
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
