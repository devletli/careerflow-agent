"""Documents: list, private file streaming, legacy download, backfill."""
import asyncio
import re
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import logger, minio_client
from app.security import require_api_key
from shared.db.models import Application, ApplicationDocument, Document, Job
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
        # Source of truth is application_documents (a doc may be shared
        # across apps); legacy documents.application_id holds only the last
        # link, so match either.
        linked_ids = select(ApplicationDocument.document_id).where(
            ApplicationDocument.application_id == application_id
        )
        stmt = stmt.where(
            (Document.application_id == application_id) | (Document.id.in_(linked_ids))
        )
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


def _slug(value: Any, maximum_length: int = 40) -> str:
    """Portable ASCII slug for filenames (same rules as cv-generator)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_")
    return (slug[:maximum_length].strip("_") or "untitled").lower()


def _extension_for(mime_type: str) -> str:
    if mime_type == "application/pdf":
        return ".pdf"
    if "wordprocessingml" in (mime_type or ""):
        return ".docx"
    return ""


def _document_filename(document: Document, job: Optional[Job] = None) -> str:
    # 1) Prefer the unique name stored at generation time:
    #    "{candidate}_{company}_{role}_{jobid8}_CV_{lang}.pdf" etc.
    #    This is already unique per job/employer.
    meta = document.metadata_json or {}
    if isinstance(meta, dict):
        stored = meta.get("filename")
        if isinstance(stored, str) and stored.strip():
            # Never leak paths; keep only the basename.
            base = PurePosixPath(stored.strip()).name
            # Ensure it still carries an extension.
            if "." not in base:
                base += _extension_for(document.mime_type)
            return base

    # 2) Fallback for legacy rows without metadata: build a unique name
    #    from company + title + type + version + short ids.
    company = ""
    title = ""
    if isinstance(meta, dict):
        company = str(meta.get("company") or "")
        title = str(meta.get("title") or "")
    if job is not None:
        company = company or getattr(job, "company", "")
        title = title or getattr(job, "title", "")
    company_slug = _slug(company or "company")
    title_slug = _slug(title or "role")
    job_short = str(document.job_id)[:8]
    doc_short = str(document.id)[:8]
    type_label = "Cover_Letter" if document.type == "cover_letter" else "CV"
    filename = (
        f"{company_slug}_{title_slug}_{job_short}_"
        f"{type_label}_{document.language}_v{document.version}_{doc_short}"
    )
    return filename + _extension_for(document.mime_type)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    download: bool = Query(default=False, description="True for attachment download, False for inline view"),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Streams a private artifact; inline view or attachment download."""
    document, content = await _stream_document_bytes(document_id, session)
    job = await session.get(Job, document.job_id)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        BytesIO(content),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'{disposition}; filename="{_document_filename(document, job)}"'},
    )


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Legacy attachment download (kept for compatibility; prefer /file)."""
    document, content = await _stream_document_bytes(document_id, session)
    job = await session.get(Job, document.job_id)
    return StreamingResponse(
        BytesIO(content),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{_document_filename(document, job)}"'},
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Deletes exactly one document version plus its MinIO object.

    Versioning is preserved: only the requested row is removed, never the
    whole (job_id, type, language) family. The MinIO object is removed only
    when no other document row still references the same (bucket, key).
    """
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    bucket, key = document.minio_bucket, document.minio_key
    # Remove snapshot links first so exact-version history stays consistent
    # even on DBs without FK enforcement (SQLite without pragma).
    links = (
        await session.execute(
            select(ApplicationDocument).where(ApplicationDocument.document_id == document.id)
        )
    ).scalars().all()
    for link in links:
        await session.delete(link)
    await session.delete(document)
    await session.flush()
    others = (
        await session.execute(
            select(Document).where(
                Document.minio_bucket == bucket,
                Document.minio_key == key,
            )
        )
    ).scalars().first()
    if others is None:
        try:
            ok = await asyncio.to_thread(minio_client.delete_object, key, bucket)
        except Exception as exc:  # noqa: BLE001 - logged, DB row already gone
            logger.error("MinIO cleanup failed for document_id=%s: %s", document_id, exc)
            ok = False
        if not ok:
            logger.error("MinIO cleanup failed for document_id=%s", document_id)
    return {"id": str(document_id), "deleted": True}
