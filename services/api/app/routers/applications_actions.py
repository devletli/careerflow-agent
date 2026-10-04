"""Applications: explicit per-application actions (execute)."""
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.confirmations import consume_confirmation_token
from app.deps import redis_bus
from app.security import require_api_key
from shared.config import settings
from shared.contracts.events import BaseEvent
from shared.db.models import Application, Job
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/applications",
    tags=["applications"],
    dependencies=[Depends(require_api_key)],
)

APPLICATION_EXECUTE_ACTIONS = {"prepare", "submit", "retry", "continue"}
# Legacy alias: older rows use READY_TO_APPLY where the dashboard uses READY_TO_SUBMIT.
READY_STATUSES = {"READY_TO_SUBMIT", "READY_TO_APPLY"}


class ApplicationExecuteRequest(BaseModel):
    action: str
    # Faz 3B: submit icin tek kullanimlik sunucu tokeni (UI onayina guvenilmez).
    confirmation_token: Optional[str] = None


@router.patch(
    "/{application_id}/execute",
    response_model=None,
)
async def execute_application_action(
    application_id: UUID,
    request: ApplicationExecuteRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any] | JSONResponse:
    """Explicit per-application action (prepare/submit/retry/continue).

    The frontend sends the semantic action explicitly; each branch maps to a
    distinct operation instead of funneling everything into one submit call.
    """
    if request.action not in APPLICATION_EXECUTE_ACTIONS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action: {request.action}.",
        )
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    status = application.status

    if request.action == "prepare":
        if status in READY_STATUSES:
            return {"id": str(application.id), "status": application.status, "action": "prepare"}
        if status != "CREATED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Prepare is only valid from CREATED (current: {status}).",
            )
        application.status = "READY_TO_SUBMIT"
        application.blocked_reason = None
        application.failure_reason = None
        await session.flush()
        return {"id": str(application.id), "status": application.status, "action": "prepare"}

    if request.action == "submit":
        if status == "SUBMITTED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Application has already been submitted (retryable=false).",
            )
        if status in ("RUNNING", "FILLING", "SUBMITTING"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Application is already running (current: {status}).",
            )
        if status == "REQUIRES_HUMAN":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Submission result is uncertain; manual review required (retryable=false).",
            )
        if status in ("BLOCKED", "FAILED"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Resolve {status} first (use retry/continue); submit forbidden (retryable=false).",
            )
        if status not in READY_STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Submit is only valid from READY_TO_SUBMIT (current: {status}).",
            )
        # Faz 3B: UI onayina guvenme; tek kullanimlik sunucu tokeni sart (B2: Redis GETDEL).
        if not await consume_confirmation_token(
            await redis_bus.get_redis(), request.confirmation_token, "submit", str(application_id)
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "A single-use confirmation token is required before submission. "
                    "Mint one via POST /api/v1/confirmations right after the user confirms."
                ),
            )
        # The browser only submits in FULL_AUTO + AUTO_SUBMIT. Reject here
        # with an actionable message instead of silently filling the form,
        # which would never produce SUBMITTED or REQUIRES_HUMAN.
        if settings.AUTOMATION_MODE != "FULL_AUTO" or not settings.AUTO_SUBMIT:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Submission is disabled in the current mode "
                    f"({settings.AUTOMATION_MODE}, AUTO_SUBMIT={settings.AUTO_SUBMIT}); "
                    "set AUTOMATION_MODE=FULL_AUTO and AUTO_SUBMIT=true to submit."
                ),
            )
        correlation_id = f"control-{uuid4().hex[:12]}"
        event = BaseEvent(
            event_type="pipeline.control.v1",
            correlation_id=correlation_id,
            entity_id=str(application.id),
            payload={
                "action": "submit_application",
                "confirmed": True,
                "application_id": str(application.id),
            },
        )
        message_id = await redis_bus.publish(event)
        return JSONResponse(
            status_code=http_status.HTTP_202_ACCEPTED,
            content={
                "status": "queued",
                "action": "submit",
                "application_id": str(application.id),
                "correlation_id": correlation_id,
                "message_id": message_id,
            },
        )

    if request.action == "retry":
        # Safe default: retry forbidden everywhere except a plain FAILED row.
        if status == "SUBMITTED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Already submitted; retry forbidden (retryable=false).",
            )
        if status == "REQUIRES_HUMAN":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ambiguous submission; retry forbidden, continue manually (retryable=false).",
            )
        if status in ("RUNNING", "FILLING", "SUBMITTING"):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Application is running (current: {status}); retry forbidden.",
            )
        if status == "BLOCKED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Blocked (e.g. CAPTCHA/MFA/login); human intervention required (retryable=false).",
            )
        if status != "FAILED":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Nothing to retry from {status} (retryable=false).",
            )
        application.status = "READY_TO_SUBMIT"
        application.failure_reason = None
        await session.flush()
        return {
            "id": str(application.id),
            "status": application.status,
            "action": "retry",
            "retryable": True,
        }

    # request.action == "continue": honest manual workflow, no fake session resume.
    if status != "REQUIRES_HUMAN":
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Continue is only valid from REQUIRES_HUMAN (current: {status}).",
        )
    job = await session.get(Job, application.job_id)
    application_url = (job.application_url or job.url) if job else None
    return {
        "id": str(application.id),
        "status": application.status,
        "action": "continue",
        "application_url": application_url,
        "manual_steps": [
            "Open the application URL in your own browser.",
            "Review the pre-filled data and documents.",
            "Submit manually only after you see the site's own confirmation.",
        ],
    }
