"""enrichment_item: add started_at / finished_at for per-item duration

Revision ID: 0006_item_started_finished
Revises: 0005_item_resolution_json
Create Date: 2026-07-08 00:00:02.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_item_started_finished"
down_revision: str | None = "0005_item_resolution_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "enrichment_item",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "finished_at")
    op.drop_column("enrichment_item", "started_at")
