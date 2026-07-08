"""enrichment_job: add started_at / finished_at for run duration

Revision ID: 0004_job_started_finished
Revises: 0003_account_and_enrichment
Create Date: 2026-07-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_job_started_finished"
down_revision: str | None = "0003_account_and_enrichment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_job",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "enrichment_job",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_job", "finished_at")
    op.drop_column("enrichment_job", "started_at")
