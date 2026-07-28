"""enrichment_item.staged_price : prix de vente lu sur la page source.

Proposé uniquement quand le catalogue n'a pas de prix (0/None) ; écrit via
l'input `price` de l'endpoint enrich Xano à l'apply (évolution Marc
2026-07-28, vérifiée live : 0 ignoré, décimal > 0 enregistré).

Revision ID: 0023_item_staged_price
Revises: 0022_item_description_html
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023_item_staged_price"
down_revision: str | None = "0022_item_description_html"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("staged_price", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "staged_price")
