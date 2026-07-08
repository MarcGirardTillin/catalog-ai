"""enrichment_item: add apply_fields_json (per-field keep/drop on apply)

Revision ID: 0007_item_apply_fields
Revises: 0006_item_started_finished
Create Date: 2026-07-08 00:00:03.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_item_apply_fields"
down_revision: str | None = "0006_item_started_finished"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("apply_fields_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "apply_fields_json")
