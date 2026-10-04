"""T7 structured JSON logging + correlation_id tests (offline)."""
import json
import logging

from shared.infra.jsonlog import JsonFormatter, correlation, install_json_logging


def _record(message: str, **extra):
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_json_with_ids():
    out = json.loads(JsonFormatter().format(_record("hello", correlation_id="c-1")))
    assert out["message"] == "hello"
    assert out["correlation_id"] == "c-1"
    assert out["level"] == "INFO" and "timestamp" in out


def test_context_binding_flows_into_records():
    with correlation("corr-9", "entity-7"):
        out = json.loads(JsonFormatter().format(_record("work")))
    assert out["correlation_id"] == "corr-9"
    assert out["entity_id"] == "entity-7"
    # Context is reset after the block.
    out2 = json.loads(JsonFormatter().format(_record("after")))
    assert out2["correlation_id"] is None


def test_install_is_idempotent_and_json(monkeypatch):
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        install_json_logging()
        install_json_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


def test_orchestrator_binds_correlation_per_event():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "services" / "orchestrator" / "app" / "worker.py").read_text(encoding="utf-8")
    assert "with correlation(event.correlation_id" in src
    assert "install_json_logging" in src


def test_api_action_logs_with_correlation_extra():
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "services" / "api" / "app" / "routers" / "pipeline.py"
    ).read_text(encoding="utf-8")
    assert 'extra={"correlation_id": correlation_id' in src
