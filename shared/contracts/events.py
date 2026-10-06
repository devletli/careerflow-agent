from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional, Type
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaseEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    version: str = "v1"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    correlation_id: str
    entity_id: str
    # Faz 4A: ayni mantiksal komutun tekrar yayinlari ayni anahtari tasir;
    # bos birakilirsa event_id kullanilir (retry yayininda korunur).
    idempotency_key: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_idempotency_key(self) -> "BaseEvent":
        if not self.idempotency_key:
            self.idempotency_key = self.event_id
        return self

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseEvent":
        return cls(**data)


class JobDiscoveredEvent(BaseEvent):
    event_type: str = "job.discovered.v1"


class JobNormalizedEvent(BaseEvent):
    event_type: str = "job.normalized.v1"


class JobMatchedEvent(BaseEvent):
    event_type: str = "job.matched.v1"


class JobQualifiedEvent(BaseEvent):
    event_type: str = "job.qualified.v1"


class DocumentsGeneratedEvent(BaseEvent):
    event_type: str = "documents.generated.v1"


class ApplicationAnalyzedEvent(BaseEvent):
    event_type: str = "application.analyzed.v1"


class ApplicationReadyEvent(BaseEvent):
    event_type: str = "application.ready.v1"


class ApplicationFilledEvent(BaseEvent):
    event_type: str = "application.filled.v1"


class ApplicationSubmittedEvent(BaseEvent):
    event_type: str = "application.submitted.v1"


class ApplicationFailedEvent(BaseEvent):
    event_type: str = "application.failed.v1"


class ApplicationBlockedEvent(BaseEvent):
    event_type: str = "application.blocked.v1"


class ApplicationRequiresHumanEvent(BaseEvent):
    event_type: str = "application.requires_human.v1"


class DiscoverySummaryEvent(BaseEvent):
    event_type: str = "discovery.summary.v1"


EVENT_TYPE_MAP: Dict[str, Type[BaseEvent]] = {
    "job.discovered.v1": JobDiscoveredEvent,
    "job.normalized.v1": JobNormalizedEvent,
    "job.matched.v1": JobMatchedEvent,
    "job.qualified.v1": JobQualifiedEvent,
    "documents.generated.v1": DocumentsGeneratedEvent,
    "application.analyzed.v1": ApplicationAnalyzedEvent,
    "application.ready.v1": ApplicationReadyEvent,
    "application.filled.v1": ApplicationFilledEvent,
    "application.submitted.v1": ApplicationSubmittedEvent,
    "application.failed.v1": ApplicationFailedEvent,
    "application.blocked.v1": ApplicationBlockedEvent,
    "application.requires_human.v1": ApplicationRequiresHumanEvent,
    "discovery.summary.v1": DiscoverySummaryEvent,
}


def parse_event(data: Any) -> BaseEvent:
    """Parses raw dictionary or JSON string into the appropriate concrete event type."""
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict or JSON string for event parsing, got {type(data)}")

    event_type = data.get("event_type") if isinstance(data, dict) else None
    event_cls = EVENT_TYPE_MAP.get(event_type, BaseEvent) if isinstance(event_type, str) else BaseEvent
    return event_cls(**data)
