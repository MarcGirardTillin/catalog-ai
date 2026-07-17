"""enrichment_item.product_title: catalog title snapshot for lists/breadcrumbs

Captured at each processing run so the review UI can label tasks by product
title instead of the opaque Tillin id. Nullable: items processed before this
revision simply keep their id-based fallback label.

Revision ID: 0020_item_product_title
Revises: 0019_multi_tenant_tokens
Create Date: 2026-07-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020_item_product_title"
down_revision: str | None = "0019_multi_tenant_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("product_title", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "product_title")
