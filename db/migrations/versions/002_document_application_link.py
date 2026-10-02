"""002_document_application_link

Revision ID: 002_document_application_link
Revises: 001_initial_schema
Create Date: 2026-10-03 00:00:00.000000

Adds a nullable application_id column to the documents table so the dashboard
can treat the Application as the central record.  Existing rows get application_id
set to NULL (they will be linked later when applications exist).

This migration is safe on both PostgreSQL and SQLite.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_document_application_link'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(
            sa.Column('application_id', sa.Uuid(), nullable=True),
        )
        batch_op.create_index('ix_documents_application_id', ['application_id'])


def downgrade() -> None:
    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_index('ix_documents_application_id')
        batch_op.drop_column('application_id')