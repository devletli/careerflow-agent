"""Pipeline event stream (read-only)."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.db.models import PipelineEvent
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/events",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
async def list_events(
    limit: int = Query(default=50, le=200),
    q: Optional[str] = Query(default=None, description="Search event type/entity/correlation id"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = select(PipelineEvent).order_by(desc(PipelineEvent.created_at)).limit(limit)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (PipelineEvent.event_type.ilike(like))
            | (PipelineEvent.entity_id.ilike(like))
            | (PipelineEvent.correlation_id.ilike(like))
        )
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
