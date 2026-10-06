"""010_job_rank_index

Revision ID: 010_job_rank_index
Revises: 009_interviews

Score-ordered listing support: rank index on job_matches, last_seen_at on
jobs (backfilled from created_at) + index for STALE sweeping.
Real column names verified against shared/db/models.py (overall_score).
Safe on PostgreSQL and SQLite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_job_rank_index'
down_revision: Union[str, None] = '009_interviews'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE jobs SET last_seen_at = created_at WHERE last_seen_at IS NULL"))
    op.create_index('ix_job_matches_rank', 'job_matches', [sa.text('overall_score DESC'), 'job_id'])
    op.create_index('ix_jobs_last_seen', 'jobs', ['last_seen_at'])


def downgrade() -> None:
    op.drop_index('ix_jobs_last_seen', table_name='jobs')
    op.drop_index('ix_job_matches_rank', table_name='job_matches')
    op.drop_column('jobs', 'last_seen_at')
