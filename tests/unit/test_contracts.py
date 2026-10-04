from uuid import uuid4
from shared.contracts.models import (
    PipelineStatus,
    QuestionClassification,
    QualificationStatus,
    NormalizedJob,
    JobMatchResult,
    ApplicationQuestionSchema,
)
from shared.contracts.events import (
    BaseEvent,
    JobDiscoveredEvent,
    JobMatchedEvent,
    JobQualifiedEvent,
    DocumentsGeneratedEvent,
    ApplicationAnalyzedEvent,
    ApplicationReadyEvent,
    ApplicationSubmittedEvent,
    ApplicationFailedEvent,
    ApplicationBlockedEvent,
    parse_event,
)


def test_base_event_serialization():
    event = BaseEvent(
        event_type="test.event.v1",
        correlation_id="corr-123",
        entity_id="ent-456",
        payload={"key": "value"},
    )
    json_data = event.to_json()
    assert "test.event.v1" in json_data
    assert "corr-123" in json_data
    assert event.version == "v1"
    assert event.event_id is not None
    assert event.timestamp is not None


def test_idempotency_key_defaults_to_event_id():
    # Faz 4A: ayni mantiksal komutun retry yayinlari ayni anahtari tasir.
    event = BaseEvent(
        event_type="test.event.v1",
        correlation_id="corr-123",
        entity_id="ent-456",
    )
    assert event.idempotency_key == event.event_id
    assert event.idempotency_key in event.to_json()


def test_idempotency_key_survives_republish_roundtrip():
    event = JobDiscoveredEvent(correlation_id="corr-1", entity_id="ent-1")
    republished = parse_event(event.to_json())
    assert republished.idempotency_key == event.idempotency_key == event.event_id


def test_explicit_idempotency_key_preserved():
    event = BaseEvent(
        event_type="test.event.v1",
        correlation_id="corr-123",
        entity_id="ent-456",
        idempotency_key="cmd-42",
    )
    assert event.idempotency_key == "cmd-42"


def test_typed_events_and_parser():
    events_to_test = [
        ("job.discovered.v1", JobDiscoveredEvent),
        ("job.matched.v1", JobMatchedEvent),
        ("job.qualified.v1", JobQualifiedEvent),
        ("documents.generated.v1", DocumentsGeneratedEvent),
        ("application.analyzed.v1", ApplicationAnalyzedEvent),
        ("application.ready.v1", ApplicationReadyEvent),
        ("application.submitted.v1", ApplicationSubmittedEvent),
        ("application.failed.v1", ApplicationFailedEvent),
        ("application.blocked.v1", ApplicationBlockedEvent),
    ]

    for event_type, cls in events_to_test:
        inst = cls(
            correlation_id="c-1",
            entity_id="e-1",
            payload={"test": True},
        )
        assert inst.event_type == event_type

        # Test parser from dict
        parsed = parse_event(inst.model_dump())
        assert isinstance(parsed, cls)
        assert parsed.correlation_id == "c-1"

        # Test parser from json string
        parsed_json = parse_event(inst.to_json())
        assert isinstance(parsed_json, cls)
        assert parsed_json.entity_id == "e-1"


def test_unknown_event_fallback():
    raw = {
        "event_type": "custom.unknown.v1",
        "correlation_id": "c-unknown",
        "entity_id": "e-unknown",
        "payload": {},
    }
    parsed = parse_event(raw)
    assert isinstance(parsed, BaseEvent)
    assert parsed.event_type == "custom.unknown.v1"


def test_pipeline_status_enum():
    assert PipelineStatus.DISCOVERED.value == "DISCOVERED"
    assert PipelineStatus.SUBMITTED.value == "SUBMITTED"
    assert PipelineStatus.READY_TO_APPLY.value == "READY_TO_APPLY"
    assert PipelineStatus.DUPLICATE.value == "DUPLICATE"


def test_normalized_job_validation():
    job = NormalizedJob(
        source="workable",
        source_job_id="w-12345",
        company="Acme Corp",
        title="AI Engineer",
        url="https://jobs.workable.com/view/12345",
    )
    assert job.company == "Acme Corp"
    assert job.status == PipelineStatus.DISCOVERED
    assert job.requirements == []


def test_job_match_result_validation():
    match = JobMatchResult(
        job_id=uuid4(),
        overall_score=96.5,
        confidence=0.92,
        qualification=QualificationStatus.QUALIFIED,
        matching_skills=["Python", "Docker", "DevOps"],
        missing_skills=[],
        explanation="Strong match with all primary requirements met",
    )
    assert match.overall_score == 96.5
    assert match.qualification == QualificationStatus.QUALIFIED


def test_question_schema():
    q = ApplicationQuestionSchema(
        key="work_auth",
        text="Are you authorized to work in Germany?",
        type="radio",
        is_required=True,
        options=["Yes", "No"],
        classification=QuestionClassification.LEGAL_OR_WORK_AUTHORIZATION,
        confidence=1.0,
    )
    assert q.classification == QuestionClassification.LEGAL_OR_WORK_AUTHORIZATION
    assert len(q.options) == 2
