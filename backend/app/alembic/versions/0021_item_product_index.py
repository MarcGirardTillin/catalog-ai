"""Index (account_id, tillin_product_id) sur enrichment_item.

Alimente l'historique d'enrichissement par produit (panneau produit :
« déjà enrichi ? écarté ? quand ? »).

Revision ID: 0021_item_product_index
Revises: 0020_item_product_title
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_item_product_index"
down_revision: str | None = "0020_item_product_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_enrichment_item_account_product",
        "enrichment_item",
        ["account_id", "tillin_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_enrichment_item_account_product", table_name="enrichment_item")
