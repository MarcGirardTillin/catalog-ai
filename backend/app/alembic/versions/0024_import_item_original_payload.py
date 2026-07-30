"""import_item.original_payload_json : le payload extrait AVANT toute édition.

Capturé au staging ; « Réinitialiser le produit » en review restaure cet
original (demande Marc 2026-07-30). Les items existants restent à NULL —
le bouton de réinitialisation n'apparaît pas pour eux.

Revision ID: 0024_item_original_payload
Revises: 0023_item_staged_price
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024_item_original_payload"
down_revision: str | None = "0023_item_staged_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_item",
        sa.Column("original_payload_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_item", "original_payload_json")
