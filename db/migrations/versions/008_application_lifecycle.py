"""008_application_lifecycle

Revision ID: 008_application_lifecycle
Revises: 007_drop_dup_indexes
Create Date: 2026-10-04 00:00:00.000000

Human application lifecycle (independent from automation `status`):
- applications.lifecycle_status / application_method / applied_at /
  next_action / next_action_due_at
- application_status_history (append-only audit)
- application_documents (authoritative per-application document snapshot;
  documents.application_id is kept for backward compatibility)
- jobs.user_status (human board state, pipeline `status` untouched)

Safe on PostgreSQL and SQLite (batch mode for column adds).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008_application_lifecycle'
down_revision: Union[str, None] = '007_drop_dup_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(sa.Column('user_status', sa.String(length=32), nullable=True))

    with op.batch_alter_table('applications') as batch_op:
        batch_op.add_column(
            sa.Column('lifecycle_status', sa.String(length=32), nullable=False, server_default='DRAFT')
        )
        batch_op.add_column(
            sa.Column('application_method', sa.String(length=16), nullable=False, server_default='AUTOMATED')
        )
        batch_op.add_column(sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('next_action', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('next_action_due_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index('ix_applications_lifecycle', ['lifecycle_status'])

    op.create_table(
        'application_status_history',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_status', sa.String(length=32), nullable=True),
        sa.Column('to_status', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='MANUAL'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'ix_app_status_history_app_created', 'application_status_history', ['application_id', 'created_at']
    )

    op.create_table(
        'application_documents',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.Uuid(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False, server_default='CV'),
        sa.Column('attached_by', sa.String(length=16), nullable=False, server_default='MANUAL'),
        sa.Column('attached_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('application_id', 'document_id', name='uq_app_documents_app_doc'),
    )
    op.create_index('ix_app_documents_app', 'application_documents', ['application_id'])
    op.create_index('ix_app_documents_doc', 'application_documents', ['document_id'])


def downgrade() -> None:
    op.drop_index('ix_app_documents_doc', table_name='application_documents')
    op.drop_index('ix_app_documents_app', table_name='application_documents')
    op.drop_table('application_documents')
    op.drop_index('ix_app_status_history_app_created', table_name='application_status_history')
    op.drop_table('application_status_history')
    with op.batch_alter_table('applications') as batch_op:
        batch_op.drop_index('ix_applications_lifecycle')
        batch_op.drop_column('next_action_due_at')
        batch_op.drop_column('next_action')
        batch_op.drop_column('applied_at')
        batch_op.drop_column('application_method')
        batch_op.drop_column('lifecycle_status')
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_column('user_status')
