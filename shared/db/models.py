from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID as PyUUID
from uuid import uuid4
from sqlalchemy import (
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Use JSONB on PostgreSQL, standard JSON on SQLite/others
JSONType = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Human/user state is separate from pipeline `status` (DISCOVERED...).
    # Lets the user say INTERESTED/ARCHIVED while the agent still reports
    # pipeline progress. NULL = no explicit user state yet.
    user_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default=None)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    application_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirements: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    publication_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    job_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="DISCOVERED")
    # Faz 3: kesif her goruste gunceller; son N gundur gorulmeyen STALE olur (silinmez).
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Relationships
    requirements_rel: Mapped[list["JobRequirement"]] = relationship(
        "JobRequirement", back_populates="job", cascade="all, delete-orphan"
    )
    matches: Mapped[list["JobMatch"]] = relationship(
        "JobMatch", back_populates="job", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="job", cascade="all, delete-orphan"
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # NOT: (source, source_job_id) icin ayri non-unique indeks YOK;
        # unique constraint'in destek indeksi ayni taramalara hizmet eder (007).
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_source_job_id"),
    )


class JobRequirement(Base):
    __tablename__ = "job_requirements"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    requirement_type: Mapped[str] = mapped_column(String(64), nullable=False)  # hard, soft, skill, experience
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extracted_skills: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped["Job"] = relationship("Job", back_populates="requirements_rel")


class JobMatch(Base):
    __tablename__ = "job_matches"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    qualification_status: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # QUALIFIED, NOT_QUALIFIED, REVIEW
    component_scores: Mapped[dict[str, float]] = mapped_column(JSONType, nullable=False, default=dict)
    hard_requirements: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    matching_skills: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    risks: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped["Job"] = relationship("Job", back_populates="matches")
    profile: Mapped[Optional["Profile"]] = relationship("Profile")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    profile_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # cv, cover_letter
    language: Mapped[str] = mapped_column(String(16), nullable=False)  # de, en
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    minio_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    minio_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/pdf")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped["Job"] = relationship("Job", back_populates="documents")
    application: Mapped[Optional["Application"]] = relationship("Application", back_populates="documents")
    profile: Mapped[Optional["Profile"]] = relationship("Profile")

    __table_args__ = (
        UniqueConstraint("job_id", "type", "language", "version", name="uq_documents_job_type_lang_ver"),
        Index("ix_documents_job_type", "job_id", "type"),
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # NOT: unique=True zaten destek indeksi kurar; ayri index=True
    # ayni kolonlara cift indeks demekti (007 ile kaldirildi).
    application_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="DISCOVERED", index=True)
    automation_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="PREPARE_APPLICATION")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submission_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    last_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Human lifecycle is separate from automation `status` (CREATED/RUNNING/...).
    # DRAFT, PREPARED, APPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN.
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    # MANUAL vs AUTOMATED: how this application was (or will be) submitted.
    application_method: Mapped[str] = mapped_column(String(16), nullable=False, default="AUTOMATED")
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_action_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    job: Mapped["Job"] = relationship("Job", back_populates="applications")
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="application")
    questions: Mapped[list["ApplicationQuestion"]] = relationship(
        "ApplicationQuestion", back_populates="application", cascade="all, delete-orphan"
    )
    answers: Mapped[list["ApplicationAnswer"]] = relationship(
        "ApplicationAnswer", back_populates="application", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        "ApplicationStatusHistory", back_populates="application", cascade="all, delete-orphan"
    )
    document_links: Mapped[list["ApplicationDocument"]] = relationship(
        "ApplicationDocument", back_populates="application", cascade="all, delete-orphan"
    )
    interviews: Mapped[list["Interview"]] = relationship(
        "Interview", back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_applications_job_id", "job_id"),
        Index("ix_applications_status_updated", "status", "updated_at"),
        Index("ix_applications_lifecycle", "lifecycle_status"),
    )


class ApplicationStatusHistory(Base):
    """Append-only lifecycle audit: DRAFT -> APPLIED -> INTERVIEW -> ..."""

    __tablename__ = "application_status_history"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    # MANUAL (user), AUTOMATED (worker), SYSTEM (seed/migration).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    application: Mapped["Application"] = relationship("Application", back_populates="status_history")

    __table_args__ = (Index("ix_app_status_history_app_created", "application_id", "created_at"),)


class ApplicationDocument(Base):
    """Authoritative per-application document snapshot.

    One row = "application A applied with exactly this document version,
    in this role, at this time". The same Document row may be linked to
    many applications (unlike the legacy documents.application_id column,
    which can only point at one). `documents.application_id` is kept for
    backward compatibility; this table is the source of truth for reads.
    Roles: CV, COVER_LETTER, OTHER.
    """

    __tablename__ = "application_documents"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="CV")
    attached_by: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    application: Mapped["Application"] = relationship("Application", back_populates="document_links")
    document: Mapped["Document"] = relationship("Document")

    __table_args__ = (
        UniqueConstraint("application_id", "document_id", name="uq_app_documents_app_doc"),
        Index("ix_app_documents_app", "application_id"),
        Index("ix_app_documents_doc", "document_id"),
    )


class Interview(Base):
    """One interview round in the human hiring process.

    Result: PENDING (upcoming / awaiting outcome), PASSED, FAILED, CANCELLED.
    Mode / round / interviewer are free text (e.g. "Technical Interview",
    "Teams", "Max Mustermann") so no enum migration is ever needed.
    """

    __tablename__ = "interviews"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    round: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    interviewer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    application: Mapped["Application"] = relationship("Application", back_populates="interviews")

    __table_args__ = (Index("ix_interviews_app_scheduled", "application_id", "scheduled_at"),)


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(64), nullable=False)  # text, select, radio, checkbox, file
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_options: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    classification: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    application: Mapped["Application"] = relationship("Application", back_populates="questions")
    answers: Mapped[list["ApplicationAnswer"]] = relationship(
        "ApplicationAnswer", back_populates="question", cascade="all, delete-orphan"
    )


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("application_questions.id", ondelete="CASCADE"), nullable=False
    )
    answer_value: Mapped[Optional[Any]] = mapped_column(JSONType, nullable=True)
    answer_source: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # SAFE_FACT, USER_PREFERENCE, LEGAL_OR_WORK_AUTHORIZATION
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    application: Mapped["Application"] = relationship("Application", back_populates="answers")
    question: Mapped["ApplicationQuestion"] = relationship("ApplicationQuestion", back_populates="answers")

    __table_args__ = (
        UniqueConstraint("application_id", "question_id", name="uq_application_answers_app_question"),
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[Optional[PyUUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)  # DISCOVERY, MATCHING, GENERATION, ANALYSIS, BROWSER_FILL
    status: Mapped[str] = mapped_column(String(64), nullable=False)  # STARTED, COMPLETED, FAILED, BLOCKED
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Faz 4A: architecture.md "her komutta idempotency_key" iddiasi.
    # Varsayilan event_id'dir (retry yayininda korunur); unique indexlenir.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_pipeline_events_type_created", "event_type", "created_at"),
        Index("ix_pipeline_events_created_at", "created_at"),
    )


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    original_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
