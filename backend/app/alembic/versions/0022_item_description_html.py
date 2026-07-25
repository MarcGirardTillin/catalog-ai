"""enrichment_item.staged_description_html : version riche de la copie.

Le copywriter produit désormais deux versions (texte brut + HTML léger) ;
le HTML part dans le champ Tillin `description_html` à l'apply (décision
Marc 2026-07-18 — le style/emojis étaient perdus en texte brut).

Revision ID: 0022_item_description_html
Revises: 0021_item_product_index
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022_item_description_html"
down_revision: str | None = "0021_item_product_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_item",
        sa.Column("staged_description_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_item", "staged_description_html")
