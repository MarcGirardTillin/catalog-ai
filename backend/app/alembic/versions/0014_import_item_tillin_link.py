"""import_item.tillin_product_id: link transferred items to Tillin products

Revision ID: 0014_import_item_tillin_link
Revises: 0013_usage_billing_snapshot
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_import_item_tillin_link"
down_revision: str | None = "0013_usage_billing_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_item",
        sa.Column("tillin_product_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_item", "tillin_product_id")
