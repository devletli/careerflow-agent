"""Applications: interview rounds (human hiring pipeline)."""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_api_key
from shared.db.models import Application, ApplicationStatusHistory, Interview, Job
from shared.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/interviews",
    tags=["interviews"],
    dependencies=[Depends(require_api_key)],
)

nested_router = APIRouter(
    prefix="/api/v1/applications",
    tags=["interviews"],
    dependencies=[Depends(require_api_key)],
)

INTERVIEW_RESULTS = frozenset({"PENDING", "PASSED", "FAILED", "CANCELLED"})


def _parse_dt(value: Any, field: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid {field}: expected ISO datetime.",
            ) from exc
    else:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field}: expected ISO datetime.",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize(
    interview: Interview, company: Optional[str] = None, title: Optional[str] = None,
    application_id: Optional[Any] = None,
) -> dict[str, Any]:
    return {
        "id": str(interview.id),
        "application_id": str(application_id or interview.application_id),
        "company": company,
        "title": title,
        "scheduled_at": interview.scheduled_at.isoformat() if interview.scheduled_at else None,
        "round": interview.round,
        "mode": interview.mode,
        "interviewer": interview.interviewer,
        "location": interview.location,
        "notes": interview.notes,
        "result": interview.result,
        "created_at": interview.created_at.isoformat() if interview.created_at else None,
        "updated_at": interview.updated_at.isoformat() if interview.updated_at else None,
    }


class InterviewCreateRequest(BaseModel):
    scheduled_at: Optional[str] = None
    round: Optional[str] = None
    mode: Optional[str] = None
    interviewer: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    result: Optional[str] = "PENDING"


class InterviewUpdateRequest(BaseModel):
    scheduled_at: Optional[str] = None
    round: Optional[str] = None
    mode: Optional[str] = None
    interviewer: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    result: Optional[str] = None


@nested_router.post("/{application_id}/interviews")
async def create_interview(
    application_id: UUID,
    request: InterviewCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Schedules an interview round; moves DRAFT/PREPARED/APPLIED -> INTERVIEW."""
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        )
    result = (request.result or "PENDING").upper()
    if result not in INTERVIEW_RESULTS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown result: {request.result}.",
        )
    if not any(
        [
            request.scheduled_at,
            (request.round or "").strip(),
            (request.mode or "").strip(),
            (request.interviewer or "").strip(),
            (request.location or "").strip(),
            (request.notes or "").strip(),
        ]
    ):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty interview: provide at least scheduled_at, round, or notes.",
        )
    interview = Interview(
        id=uuid4(),
        application_id=application.id,
        scheduled_at=_parse_dt(request.scheduled_at, "scheduled_at"),
        round=request.round or None,
        mode=request.mode or None,
        interviewer=request.interviewer or None,
        location=request.location or None,
        notes=request.notes or None,
        result=result,
    )
    session.add(interview)
    # Human lifecycle follows the real process: a scheduled round means
    # the application is now in INTERVIEW (recorded in history).
    if application.lifecycle_status in ("DRAFT", "PREPARED", "APPLIED"):
        previous = application.lifecycle_status
        application.lifecycle_status = "INTERVIEW"
        session.add(
            ApplicationStatusHistory(
                id=uuid4(),
                application_id=application.id,
                from_status=previous,
                to_status="INTERVIEW",
                source="MANUAL",
                note="Interview scheduled.",
            )
        )
    await session.flush()
    return _serialize(interview)


@router.get("")
async def list_interviews(
    application_id: Optional[UUID] = Query(default=None),
    upcoming: bool = Query(default=False, description="Only PENDING with scheduled_at >= now"),
    limit: int = Query(default=100, le=100),
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(Interview, Job.company, Job.title, Application.id)
        .join(Application, Application.id == Interview.application_id)
        .join(Job, Job.id == Application.job_id)
        .order_by(Interview.scheduled_at.asc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    if application_id is not None:
        stmt = stmt.where(Interview.application_id == application_id)
    if upcoming:
        stmt = stmt.where(
            Interview.result == "PENDING",
            Interview.scheduled_at.is_not(None),
            Interview.scheduled_at >= datetime.now(timezone.utc),
        )
    rows = (await session.execute(stmt)).all()
    return [_serialize(i, company, title, app_id) for i, company, title, app_id in rows]


@router.patch("/{interview_id}")
async def update_interview(
    interview_id: UUID,
    request: InterviewUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    interview = await session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Interview not found.",
        )
    if "scheduled_at" in request.model_fields_set:
        interview.scheduled_at = _parse_dt(request.scheduled_at, "scheduled_at")
    for field in ("round", "mode", "interviewer", "location", "notes"):
        if field in request.model_fields_set:
            setattr(interview, field, getattr(request, field) or None)
    if request.result is not None:
        result = request.result.upper()
        if result not in INTERVIEW_RESULTS:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown result: {request.result}.",
            )
        interview.result = result
    await session.flush()
    return _serialize(interview)


@router.delete("/{interview_id}")
async def delete_interview(
    interview_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    interview = await session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Interview not found.",
        )
    await session.delete(interview)
    await session.flush()
    return {"id": str(interview_id), "deleted": True}
