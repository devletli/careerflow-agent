"""Structured JSON logging with correlation ids (T7 observability).

Opt-in via settings.LOG_FORMAT == "json". Every record carries
`correlation_id` (plus job_id/application_id when bound), so a single
pipeline event can be traced across services. Works alongside the PII
redaction filter (redaction runs first, JSON encoding second).
"""
import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
_entity_id: contextvars.ContextVar[str] = contextvars.ContextVar("entity_id", default="")


class correlation:
    """Binds correlation/entity ids for the current async context."""

    def __init__(self, correlation_id: str = "", entity_id: str = ""):
        self.correlation_id = correlation_id
        self.entity_id = entity_id
        self._tokens: list = []

    def __enter__(self) -> "correlation":
        self._tokens = [
            _correlation_id.set(self.correlation_id),
            _entity_id.set(self.entity_id),
        ]
        return self

    def __exit__(self, *args: Any) -> None:
        _correlation_id.reset(self._tokens[0])
        _entity_id.reset(self._tokens[1])


class JsonFormatter(logging.Formatter):
    """Single-line JSON records: timestamp, level, logger, message, ids."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or _correlation_id.get() or None,
            "entity_id": getattr(record, "entity_id", None) or _entity_id.get() or None,
        }
        return json.dumps(payload, ensure_ascii=False)


def install_json_logging(level: Optional[int] = None) -> None:
    """Replaces root handlers with a JSON handler (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level if level is not None else logging.INFO)
