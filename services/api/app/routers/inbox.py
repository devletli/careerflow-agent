"""Overview "Bugün" eylem kutusu: müdahale sayaçları (F3)."""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.db.models import Application, Job, JobMatch
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1",
    tags=["inbox"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/inbox")
async def inbox(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Bugün neye bakmalı? Tek bakışta müdahale sayaçları.

    Kolon adları koda göredir: JobMatch.qualification_status (band yok),
    Job.created_at (first_seen_at yok).
    """
    by_status = dict(
        (
            await session.execute(
                select(Application.status, func.count()).group_by(Application.status)
            )
        ).all()
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    new_strong = await session.scalar(
        select(func.count())
        .select_from(JobMatch)
        .join(Job, Job.id == JobMatch.job_id)
        .where(JobMatch.qualification_status == "QUALIFIED", Job.created_at > cutoff)
    )
    return {
        "needs_you": by_status.get("REQUIRES_HUMAN", 0),
        "ready": by_status.get("READY_TO_SUBMIT", 0),
        "failed": by_status.get("FAILED", 0),
        "to_prepare": by_status.get("CREATED", 0),
        "new_strong_matches": new_strong or 0,
    }
