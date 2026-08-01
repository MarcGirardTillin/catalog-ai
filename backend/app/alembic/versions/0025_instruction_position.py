"""instruction_template.position : ordre d'affichage choisi par l'utilisateur.

NULL = jamais ordonnée (tri par nom en repli, après les positionnées) —
demande Marc 2026-07-31 : réordonner les instructions d'enrichissement.

Revision ID: 0025_instruction_position
Revises: 0024_item_original_payload
Create Date: 2026-07-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025_instruction_position"
down_revision: str | None = "0024_item_original_payload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "instruction_template",
        sa.Column("position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instruction_template", "position")
