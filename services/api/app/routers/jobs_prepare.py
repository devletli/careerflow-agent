"""Jobs: toplu "Hazırla" (F4). Onaylı ama tarayıcı aksiyonu değil.

Akış (mevcut komutlar, sıra ve korumalarla):
  job → uygunluk (band + fingerprint idempotency + eligibility)
  → job.qualified.v1 olayı → cv-generator (belge) → analyzer (form analizi)
  → doldurmaya hazır. fill/submit komutları ASLA çağrılmaz; onay token'ı
  gerekmez (tarayıcı aksiyonu değil), UI onay diyaloğu yeter.
Sınır sunucuda zorlanır (Pydantic max 20); çift tıklama Redis NX kilidine
takar (409). Skor mantığı, kapılar ve rate limit'ler aynen korunur.
"""
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import redis_bus
from app.security import require_api_key
from shared.contracts.events import JobQualifiedEvent
from shared.contracts.fingerprint import compute_application_fingerprint
from shared.db.models import Job, JobMatch
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)

PREPARE_BATCH_LOCK_KEY = "lock:prepare_batch"
PREPARE_BATCH_LOCK_TTL_SECONDS = 600
# orchestrator _handle_application_analyzed ile aynı varsayılan aday.
PREPARE_CANDIDATE_ID = "default_candidate"


class PrepareBatch(BaseModel):
    job_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    include_review: bool = False  # REVIEW yalnızca bilinçli seçimle


@router.post("/prepare", status_code=http_status.HTTP_202_ACCEPTED)
async def prepare_batch(
    body: PrepareBatch,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Seçili ilanları hazırlık zincirine sokar (belge + form analizi).

    Idempotent: aynı fingerprint ikinci kez işlenmez (exists). fill/submit
    olayları bu uçtan HİÇ yayınlanmaz.
    """
    from services.orchestrator.app.duplicate_detector import (
        check_submission_eligibility as _eligible,
        find_existing_application as _existing,
    )

    redis = await redis_bus.get_redis()
    locked = await redis.set(
        PREPARE_BATCH_LOCK_KEY, "1", nx=True, ex=PREPARE_BATCH_LOCK_TTL_SECONDS
    )
    if not locked:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Bir toplu hazırlık zaten çalışıyor.",
        )
    correlation_id = f"prepare-{uuid4().hex[:12]}"
    results: list[dict[str, Any]] = []
    try:
        for job_id in body.job_ids:
            job = await session.get(Job, job_id)
            if job is None:
                results.append({"job_id": str(job_id), "result": "rejected", "reason": "Job not found."})
                continue
            match = (
                await session.execute(select(JobMatch).where(JobMatch.job_id == job.id))
            ).scalars().first()
            if match is None:
                results.append({"job_id": str(job_id), "result": "rejected", "reason": "Job has no match yet."})
                continue
            band = (match.qualification_status or "").upper()
            if band == "NOT_QUALIFIED":
                results.append({"job_id": str(job_id), "result": "rejected", "reason": "NOT_QUALIFIED jobs are never prepared."})
                continue
            if band == "REVIEW" and not body.include_review:
                results.append({"job_id": str(job_id), "result": "rejected", "reason": "REVIEW needs include_review=true."})
                continue
            app_fp = compute_application_fingerprint(PREPARE_CANDIDATE_ID, job.job_fingerprint)
            eligible, reason = await _eligible(session, app_fp)
            if not eligible:
                results.append({"job_id": str(job_id), "result": "rejected", "reason": reason or "Not eligible."})
                continue
            if await _existing(session, app_fp) is not None:
                results.append({"job_id": str(job_id), "result": "exists", "reason": "Same fingerprint already prepared."})
                continue
            event = JobQualifiedEvent(
                correlation_id=correlation_id,
                entity_id=str(job.id),
                payload={"overall_score": match.overall_score, "qualification": match.qualification_status},
            )
            await redis_bus.publish(event)
            results.append({"job_id": str(job_id), "result": "accepted"})
        return {"status": "queued", "correlation_id": correlation_id, "results": results}
    finally:
        try:
            await redis.delete(PREPARE_BATCH_LOCK_KEY)
        except Exception:
            pass
