"""007_drop_duplicate_indexes

Revision ID: 007_drop_dup_indexes
Revises: 006_drop_site_adapters
Create Date: 2026-10-04 00:00:00.000000

Gorev 5: pg_index taramasi ayni kolonlarda cift indeks buldu:
- jobs(source, source_job_id): uq + non-unique ix (ayni)
- applications(application_fingerprint): uq + non-unique ix (ayni)

Unique constraint'in destek indeksi esitlik taramalarina aynen hizmet
eder; non-unique kopyalar yalnizca yazma maliyetiydi. Kaldirilir.
Model tarafi da ayni sekilde sadelestirildi (create_all paritesi).

DDL-only, veri degisikligi yok.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '007_drop_dup_indexes'
down_revision: Union[str, None] = '006_drop_site_adapters'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_jobs_source_source_job_id', table_name='jobs')
    op.drop_index('ix_applications_application_fingerprint', table_name='applications')


def downgrade() -> None:
    op.create_index(
        'ix_applications_application_fingerprint', 'applications', ['application_fingerprint']
    )
    op.create_index(
        'ix_jobs_source_source_job_id', 'jobs', ['source', 'source_job_id']
    )
