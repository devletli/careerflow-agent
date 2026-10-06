"""Skor dagilimi: Overview mini grafigi (F5). Eşik yalnızca gösterim."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.config import settings
from shared.db.models import JobMatch
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/stats",
    tags=["stats"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/score-distribution")
async def score_distribution(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """10'luk kovalar + band sayıları + en yüksek skor.

    Skor 100 son kovadadır (least(floor(s/10), 9)); boş kovalar sıfır
    doldurulur. threshold yalnızca gösterimdir, eşik DEĞİŞTİRİLMEZ.
    """
    bucket = case(
        (JobMatch.overall_score >= 100, 9),
        else_=cast(JobMatch.overall_score / 10, Integer),
    ).label("b")
    rows = (await session.execute(select(bucket, func.count()).group_by(bucket))).all()
    counts = {int(b): c for b, c in rows}
    buckets = [{"from": i * 10, "to": i * 10 + 10, "count": counts.get(i, 0)} for i in range(10)]
    band_rows = (
        await session.execute(
            select(JobMatch.qualification_status, func.count()).group_by(JobMatch.qualification_status)
        )
    ).all()
    bands = {str(k): c for k, c in band_rows}
    max_score = await session.scalar(select(func.max(JobMatch.overall_score)))
    scored = await session.scalar(select(func.count(JobMatch.id))) or 0
    return {
        "buckets": buckets,
        "bands": bands,
        "max_score": max_score,
        "threshold": settings.MIN_MATCH_SCORE,
        "scored": scored,
    }
