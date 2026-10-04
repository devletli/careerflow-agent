"""004_events_idempotency_key

Revision ID: 004_events_idempotency_key
Revises: 003_dashboard_query_indexes
Create Date: 2026-10-04 00:00:00.000000

Faz 4A: architecture.md "her komutta idempotency_key + correlation_id"
iddiasini koda tasir. correlation_id zaten vardi; idempotency_key
pipeline_events'e eklenir, mevcut satirlar event_id'den doldurulur
(retry yayininda korundugu icin birebir esdegerdir) ve unique indexlenir.

PostgreSQL + SQLite uyumlu (batch modu, ham UPDATE yok).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_events_idempotency_key'
down_revision: Union[str, None] = '003_dashboard_query_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('pipeline_events') as batch_op:
        batch_op.add_column(
            sa.Column('idempotency_key', sa.String(128), nullable=True),
        )
    op.execute(
        sa.text(
            "UPDATE pipeline_events SET idempotency_key = CAST(event_id AS CHAR(36)) "
            "WHERE idempotency_key IS NULL"
        )
    )
    with op.batch_alter_table('pipeline_events') as batch_op:
        batch_op.alter_column('idempotency_key', nullable=False)
        batch_op.create_unique_constraint(
            'uq_pipeline_events_idempotency_key', ['idempotency_key']
        )


def downgrade() -> None:
    with op.batch_alter_table('pipeline_events') as batch_op:
        batch_op.drop_constraint(
            'uq_pipeline_events_idempotency_key', type_='unique'
        )
        batch_op.drop_column('idempotency_key')
