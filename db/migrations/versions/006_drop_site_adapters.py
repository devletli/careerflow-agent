"""006_drop_site_adapters

Revision ID: 006_drop_site_adapters
Revises: 005_query_indexes
Create Date: 2026-10-04 00:00:00.000000

Faz 5B: `site_adapters` DB tablosu hicbir kod tarafindan okunmuyor/
yazilmiyordu (kant: repo capinda taramada yalnizca DDL + dokuman
gecer; tum adapter cozumu kod-ici registry'dedir:
browser/site_adapters/registry.py). Ayrica isim, submission-tarafi
SiteAdapter Protocolu ile karisiyordu. Tablo kaldirilir.

Geri donus (downgrade) 001'deki tanimi birebir geri kurar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_drop_site_adapters'
down_revision: Union[str, None] = '005_query_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('site_adapters')


def downgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB

    op.create_table(
        'site_adapters',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=64), nullable=False, unique=True),
        sa.Column('domain_pattern', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('adapter_class', sa.String(length=255), nullable=False),
        sa.Column('capabilities', JSONB, nullable=False, server_default='{}'),
        sa.Column('rate_limit_hourly', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('rate_limit_daily', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
