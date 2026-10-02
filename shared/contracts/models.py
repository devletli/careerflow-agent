from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class PipelineStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    MATCHED = "MATCHED"
    QUALIFIED = "QUALIFIED"
    DOCUMENTS_READY = "DOCUMENTS_READY"
    FORM_ANALYZED = "FORM_ANALYZED"
    READY_TO_APPLY = "READY_TO_APPLY"
    FILLING = "FILLING"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"
    DOC_REVIEW_REQUIRED = "DOC_REVIEW_REQUIRED"


class AutomationMode(str, Enum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    MATCH_ONLY = "MATCH_ONLY"
    DOCUMENTS = "DOCUMENTS"
    PREPARE_APPLICATION = "PREPARE_APPLICATION"
    FULL_AUTO = "FULL_AUTO"


class QuestionClassification(str, Enum):
    SAFE_FACT = "SAFE_FACT"
    SAFE_TRANSFORMATION = "SAFE_TRANSFORMATION"
    USER_PREFERENCE = "USER_PREFERENCE"
    LEGAL_OR_WORK_AUTHORIZATION = "LEGAL_OR_WORK_AUTHORIZATION"
    UNKNOWN = "UNKNOWN"


class QualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    REVIEW = "REVIEW"


class NormalizedJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[UUID] = None
    source: str
    source_job_id: str
    company: str
    title: str
    url: str
    application_url: Optional[str] = None
    location: Optional[str] = None
    remote_status: Optional[str] = None
    description: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    publication_metadata: Dict[str, Any] = Field(default_factory=dict)
    job_fingerprint: Optional[str] = None
    status: PipelineStatus = PipelineStatus.DISCOVERED
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class JobMatchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    profile_id: Optional[UUID] = None
    overall_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    qualification: QualificationStatus
    component_scores: Dict[str, float] = Field(default_factory=dict)
    hard_requirements: List[str] = Field(default_factory=list)
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    explanation: str = ""


class GeneratedDocument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[UUID] = None
    job_id: UUID
    application_id: Optional[UUID] = None
    profile_id: Optional[UUID] = None
    type: str  # "cv" | "cover_letter"
    language: str  # "de" | "en"
    version: int = 1
    minio_bucket: str
    minio_key: str
    file_path: Optional[str] = None
    mime_type: str = "application/pdf"
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApplicationQuestionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    text: str
    type: str  # text, select, radio, checkbox, file, textarea
    is_required: bool = True
    options: List[str] = Field(default_factory=list)
    classification: QuestionClassification = QuestionClassification.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ApplicationAnswerSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_key: str
    value: Any
    source: str  # SAFE_FACT, USER_PREFERENCE, LEGAL_OR_WORK_AUTHORIZATION
    is_verified: bool = False
