from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
    UUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base: Any = declarative_base()

# Use JSONB on PostgreSQL, standard JSON on SQLite/others
JSONType = JSON().with_variant(JSONB, "postgresql")


def utc_now():
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_data = Column(JSONType, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source = Column(String(64), nullable=False)
    source_job_id = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    application_url = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)
    remote_status = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    requirements = Column(JSONType, nullable=False, default=list)
    publication_metadata = Column(JSONType, nullable=False, default=dict)
    job_fingerprint = Column(String(64), nullable=False, index=True)
    status = Column(String(64), nullable=False, default="DISCOVERED")
    raw_data = Column(JSONType, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    requirements_rel = relationship("JobRequirement", back_populates="job", cascade="all, delete-orphan")
    matches = relationship("JobMatch", back_populates="job", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="job", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_source_job_id"),
        Index("ix_jobs_source_source_job_id", "source", "source_job_id"),
    )


class JobRequirement(Base):
    __tablename__ = "job_requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    requirement_type = Column(String(64), nullable=False)  # hard, soft, skill, experience
    description = Column(Text, nullable=False)
    is_mandatory = Column(Boolean, nullable=False, default=False)
    extracted_skills = Column(JSONType, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    job = relationship("Job", back_populates="requirements_rel")


class JobMatch(Base):
    __tablename__ = "job_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    overall_score = Column(Float, nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    qualification_status = Column(String(64), nullable=False)  # QUALIFIED, NOT_QUALIFIED, REVIEW
    component_scores = Column(JSONType, nullable=False, default=dict)
    hard_requirements = Column(JSONType, nullable=False, default=list)
    matching_skills = Column(JSONType, nullable=False, default=list)
    missing_skills = Column(JSONType, nullable=False, default=list)
    risks = Column(JSONType, nullable=False, default=list)
    explanation = Column(Text, nullable=True)
    scored_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    job = relationship("Job", back_populates="matches")
    profile = relationship("Profile")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(64), nullable=False)  # cv, cover_letter
    language = Column(String(16), nullable=False)  # de, en
    version = Column(Integer, nullable=False, default=1)
    file_path = Column(Text, nullable=True)
    minio_bucket = Column(String(128), nullable=False)
    minio_key = Column(String(512), nullable=False)
    mime_type = Column(String(128), nullable=False, default="application/pdf")
    content_hash = Column(String(64), nullable=False)
    metadata_json = Column(JSONType, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    job = relationship("Job", back_populates="documents")
    application = relationship("Application", back_populates="documents")
    profile = relationship("Profile")

    __table_args__ = (
        UniqueConstraint("job_id", "type", "language", "version", name="uq_documents_job_type_lang_ver"),
    )


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id = Column(String(128), nullable=False)
    application_fingerprint = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(64), nullable=False, default="DISCOVERED", index=True)
    automation_mode = Column(String(64), nullable=False, default="PREPARE_APPLICATION")
    attempts = Column(Integer, nullable=False, default=0)
    blocked_reason = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    submission_metadata = Column(JSONType, nullable=False, default=dict)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    job = relationship("Job", back_populates="applications")
    documents = relationship("Document", back_populates="application")
    questions = relationship("ApplicationQuestion", back_populates="application", cascade="all, delete-orphan")
    answers = relationship("ApplicationAnswer", back_populates="application", cascade="all, delete-orphan")


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    question_key = Column(String(255), nullable=False)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(64), nullable=False)  # text, select, radio, checkbox, file
    is_required = Column(Boolean, nullable=False, default=True)
    raw_options = Column(JSONType, nullable=False, default=list)
    classification = Column(String(64), nullable=False, default="UNKNOWN")
    confidence = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    application = relationship("Application", back_populates="questions")
    answers = relationship("ApplicationAnswer", back_populates="question", cascade="all, delete-orphan")


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(UUID(as_uuid=True), ForeignKey("application_questions.id", ondelete="CASCADE"), nullable=False)
    answer_value = Column(JSONType, nullable=True)
    answer_source = Column(String(64), nullable=False)  # SAFE_FACT, USER_PREFERENCE, LEGAL_OR_WORK_AUTHORIZATION
    is_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    application = relationship("Application", back_populates="answers")
    question = relationship("ApplicationQuestion", back_populates="answers")

    __table_args__ = (
        UniqueConstraint("application_id", "question_id", name="uq_application_answers_app_question"),
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    run_type = Column(String(64), nullable=False)  # DISCOVERY, MATCHING, GENERATION, ANALYSIS, BROWSER_FILL
    status = Column(String(64), nullable=False)  # STARTED, COMPLETED, FAILED, BLOCKED
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    log_path = Column(Text, nullable=True)
    trace_path = Column(Text, nullable=True)
    screenshot_path = Column(Text, nullable=True)
    metadata_json = Column(JSONType, nullable=False, default=dict)


class SiteAdapter(Base):
    __tablename__ = "site_adapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(64), unique=True, nullable=False)
    domain_pattern = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    adapter_class = Column(String(255), nullable=False)
    capabilities = Column(JSONType, nullable=False, default=dict)
    rate_limit_hourly = Column(Integer, nullable=False, default=5)
    rate_limit_daily = Column(Integer, nullable=False, default=20)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(UUID(as_uuid=True), unique=True, nullable=False)
    event_type = Column(String(128), nullable=False)
    version = Column(String(16), nullable=False, default="v1")
    correlation_id = Column(String(128), nullable=False)
    entity_id = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=False)
    payload = Column(JSONType, nullable=False, default=dict)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_pipeline_events_type_created", "event_type", "created_at"),
    )


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    original_event_id = Column(String(128), nullable=False)
    event_type = Column(String(128), nullable=False)
    payload = Column(JSONType, nullable=False, default=dict)
    error_message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
