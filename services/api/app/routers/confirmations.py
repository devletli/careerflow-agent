"""Single-use confirmation tokens (Faz 3B)."""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel

from app import confirmations
from app.deps import redis_bus
from app.security import require_api_key

router = APIRouter(
    prefix="/api/v1/confirmations",
    tags=["confirmations"],
    dependencies=[Depends(require_api_key)],
)


class ConfirmationRequest(BaseModel):
    action: str
    application_id: Optional[UUID] = None


@router.post("")
async def create_confirmation(request: ConfirmationRequest) -> dict[str, Any]:
    """Browser aksiyonu icin tek kullanimlik onay tokeni uretir.

    Dashboard, kullanicinin acik onayinin HEMEN ardindan bunu cagirir ve
    tokeni aksiyon istegiyle birlikte gonderir. Token 5 dakika gecerlidir.
    """
    if request.action in {"submit", "submit_application"} and request.application_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An application_id is required to confirm a submission.",
        )
    try:
        token, ttl = await confirmations.mint_confirmation_token(
            await redis_bus.get_redis(),
            request.action,
            str(request.application_id) if request.application_id else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return {"confirmation_token": token, "expires_in": ttl}
