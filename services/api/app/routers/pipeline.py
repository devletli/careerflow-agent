"""Pipeline control actions (queue worker runs)."""
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.confirmations import consume_confirmation_token
from app.deps import logger, redis_bus
from app.security import require_api_key
from shared.contracts.events import BaseEvent
from shared.db.models import Application
from shared.db.session import get_db_session
from shared.infra import rate_limit

router = APIRouter(
    prefix="/api/v1/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_api_key)],
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
    # Faz 3B: fill/submit icin tek kullanimlik sunucu tokeni (UI onayina guvenilmez).
    confirmation_token: Optional[str] = None


@router.post("/actions", status_code=http_status.HTTP_202_ACCEPTED)
async def run_pipeline_action(
    request: PipelineControlRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
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
    # Faz 3B: UI onay bayragi yetmez; tek kullanimlik sunucu tokeni sart (B2: Redis GETDEL).
    if request.action in CONFIRMATION_REQUIRED_ACTIONS and not await consume_confirmation_token(
        await redis_bus.get_redis(),
        request.confirmation_token,
        request.action,
        str(request.application_id) if request.application_id else None,
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "A single-use confirmation token is required before this browser action. "
                "Mint one via POST /api/v1/confirmations right after the user confirms."
            ),
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

    try:
        await rate_limit.check_action_limit(request.action, await redis_bus.get_redis())
    except rate_limit.RateLimited as exc:
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {exc.action}; retry later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

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
