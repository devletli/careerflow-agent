"""009_interviews

Revision ID: 009_interviews
Revises: 008_application_lifecycle
Create Date: 2026-10-05 00:00:00.000000

Human hiring pipeline: one row per interview round.
Safe on PostgreSQL and SQLite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009_interviews'
down_revision: Union[str, None] = '008_application_lifecycle'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'interviews',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('round', sa.String(length=128), nullable=True),
        sa.Column('mode', sa.String(length=64), nullable=True),
        sa.Column('interviewer', sa.String(length=255), nullable=True),
        sa.Column('location', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('result', sa.String(length=32), nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_interviews_app_scheduled', 'interviews', ['application_id', 'scheduled_at'])


def downgrade() -> None:
    op.drop_index('ix_interviews_app_scheduled', table_name='interviews')
    op.drop_table('interviews')
