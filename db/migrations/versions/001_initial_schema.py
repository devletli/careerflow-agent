"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    # 1. profiles
    op.create_table(
        'profiles',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('candidate_data', JSONType, nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 2. jobs
    op.create_table(
        'jobs',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('source_job_id', sa.String(length=255), nullable=False),
        sa.Column('company', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('application_url', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('remote_status', sa.String(length=64), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('requirements', JSONType, nullable=False, server_default='[]'),
        sa.Column('publication_metadata', JSONType, nullable=False, server_default='{}'),
        sa.Column('job_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='DISCOVERED'),
        sa.Column('raw_data', JSONType, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('source', 'source_job_id', name='uq_jobs_source_source_job_id'),
    )
    op.create_index('ix_jobs_source_source_job_id', 'jobs', ['source', 'source_job_id'])
    op.create_index('ix_jobs_job_fingerprint', 'jobs', ['job_fingerprint'])

    # 3. job_requirements
    op.create_table(
        'job_requirements',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requirement_type', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('extracted_skills', JSONType, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 4. job_matches
    op.create_table(
        'job_matches',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('profile_id', sa.UUID(as_uuid=True), sa.ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('overall_score', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('qualification_status', sa.String(length=64), nullable=False),
        sa.Column('component_scores', JSONType, nullable=False, server_default='{}'),
        sa.Column('hard_requirements', JSONType, nullable=False, server_default='[]'),
        sa.Column('matching_skills', JSONType, nullable=False, server_default='[]'),
        sa.Column('missing_skills', JSONType, nullable=False, server_default='[]'),
        sa.Column('risks', JSONType, nullable=False, server_default='[]'),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_job_matches_overall_score', 'job_matches', ['overall_score'])

    # 5. documents
    op.create_table(
        'documents',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('profile_id', sa.UUID(as_uuid=True), sa.ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('type', sa.String(length=64), nullable=False),
        sa.Column('language', sa.String(length=16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('file_path', sa.Text(), nullable=True),
        sa.Column('minio_bucket', sa.String(length=128), nullable=False),
        sa.Column('minio_key', sa.String(length=512), nullable=False),
        sa.Column('mime_type', sa.String(length=128), nullable=False, server_default='application/pdf'),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('metadata_json', JSONType, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('job_id', 'type', 'language', 'version', name='uq_documents_job_type_lang_ver'),
    )

    # 6. applications
    op.create_table(
        'applications',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('candidate_id', sa.String(length=128), nullable=False),
        sa.Column('application_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=64), nullable=False, server_default='DISCOVERED'),
        sa.Column('automation_mode', sa.String(length=64), nullable=False, server_default='PREPARE_APPLICATION'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('submission_metadata', JSONType, nullable=False, server_default='{}'),
        sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('application_fingerprint', name='uq_applications_fingerprint'),
    )
    op.create_index('ix_applications_application_fingerprint', 'applications', ['application_fingerprint'])
    op.create_index('ix_applications_status', 'applications', ['status'])

    # 7. application_questions
    op.create_table(
        'application_questions',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', sa.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_key', sa.String(length=255), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('question_type', sa.String(length=64), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('raw_options', JSONType, nullable=False, server_default='[]'),
        sa.Column('classification', sa.String(length=64), nullable=False, server_default='UNKNOWN'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 8. application_answers
    op.create_table(
        'application_answers',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', sa.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_id', sa.UUID(as_uuid=True), sa.ForeignKey('application_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('answer_value', JSONType, nullable=True),
        sa.Column('answer_source', sa.String(length=64), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('application_id', 'question_id', name='uq_application_answers_app_question'),
    )

    # 9. automation_runs
    op.create_table(
        'automation_runs',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', sa.UUID(as_uuid=True), sa.ForeignKey('applications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('job_id', sa.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('run_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('log_path', sa.Text(), nullable=True),
        sa.Column('trace_path', sa.Text(), nullable=True),
        sa.Column('screenshot_path', sa.Text(), nullable=True),
        sa.Column('metadata_json', JSONType, nullable=False, server_default='{}'),
    )

    # 10. site_adapters
    op.create_table(
        'site_adapters',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=64), nullable=False, unique=True),
        sa.Column('domain_pattern', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('adapter_class', sa.String(length=255), nullable=False),
        sa.Column('capabilities', JSONType, nullable=False, server_default='{}'),
        sa.Column('rate_limit_hourly', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('rate_limit_daily', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 11. pipeline_events
    op.create_table(
        'pipeline_events',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_id', sa.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('event_type', sa.String(length=128), nullable=False),
        sa.Column('version', sa.String(length=16), nullable=False, server_default='v1'),
        sa.Column('correlation_id', sa.String(length=128), nullable=False),
        sa.Column('entity_id', sa.String(length=128), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('payload', JSONType, nullable=False, server_default='{}'),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_pipeline_events_type_created', 'pipeline_events', ['event_type', 'created_at'])

    # 12. dead_letter_events
    op.create_table(
        'dead_letter_events',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('original_event_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=128), nullable=False),
        sa.Column('payload', JSONType, nullable=False, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('dead_letter_events')
    op.drop_index('ix_pipeline_events_type_created', table_name='pipeline_events')
    op.drop_table('pipeline_events')
    op.drop_table('site_adapters')
    op.drop_table('automation_runs')
    op.drop_table('application_answers')
    op.drop_table('application_questions')
    op.drop_index('ix_applications_status', table_name='applications')
    op.drop_index('ix_applications_application_fingerprint', table_name='applications')
    op.drop_table('applications')
    op.drop_table('documents')
    op.drop_index('ix_job_matches_overall_score', table_name='job_matches')
    op.drop_table('job_matches')
    op.drop_table('job_requirements')
    op.drop_index('ix_jobs_job_fingerprint', table_name='jobs')
    op.drop_index('ix_jobs_source_source_job_id', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('profiles')
