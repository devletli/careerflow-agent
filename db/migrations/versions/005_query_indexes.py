"""005_query_indexes

Revision ID: 005_query_indexes
Revises: 004_events_idempotency_key
Create Date: 2026-10-04 00:00:00.000000

Faz 4E: yama.mdSnippet'teki dort indeksten eksik ikisi:
- ix_applications_job_id: application<->job join ve per-app sorgulari.
- ix_documents_job_type: job belgeleri + latest-hesabi.

Diger ikisi 003'te vardi (ix_applications_status_updated,
ix_pipeline_events_created_at). DDL-only, veri degisikligi yok;
PostgreSQL + SQLite uyumlu.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005_query_indexes'
down_revision: Union[str, None] = '004_events_idempotency_key'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_applications_job_id', 'applications', ['job_id'])
    op.create_index('ix_documents_job_type', 'documents', ['job_id', 'type'])


def downgrade() -> None:
    op.drop_index('ix_documents_job_type', table_name='documents')
    op.drop_index('ix_applications_job_id', table_name='applications')
