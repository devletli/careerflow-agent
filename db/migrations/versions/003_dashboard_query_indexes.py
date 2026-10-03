"""003_dashboard_query_indexes

Revision ID: 003_dashboard_query_indexes
Revises: 002_document_application_link
Create Date: 2026-10-04 00:00:00.000000

Adds the dashboard hot-path indexes from yama.md Faz 5-C:
- applications(status, updated_at): status-filtered application lists.
- pipeline_events(created_at): the event-stream ORDER BY created_at query.

Note: yama.md names the events table "events"; the actual table in this
repository is "pipeline_events", so the index targets that table.

Safe on both PostgreSQL and SQLite (plain CREATE INDEX, no data change).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '003_dashboard_query_indexes'
down_revision: Union[str, None] = '002_document_application_link'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_applications_status_updated', 'applications', ['status', 'updated_at']
    )
    op.create_index(
        'ix_pipeline_events_created_at', 'pipeline_events', ['created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_pipeline_events_created_at', table_name='pipeline_events')
    op.drop_index('ix_applications_status_updated', table_name='applications')
