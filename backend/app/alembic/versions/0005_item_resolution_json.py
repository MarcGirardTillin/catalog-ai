"""enrichment_item: add resolution_json (reason + candidate matches)

Revision ID: 0005_item_resolution_json
Revises: 0004_job_started_finished
Create Date: 2026-07-08 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_item_resolution_json"
down_revision: str | None = "0004_job_started_finished"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("resolution_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "resolution_json")
