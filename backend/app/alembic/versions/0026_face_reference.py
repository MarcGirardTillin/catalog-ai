"""Table face_reference : visages mannequins du compte (face swap FASHN).

Bibliothèque par compte avec prévisualisation (réglages boutique + studio),
utilisée par le geste « Remplacer le mannequin » (validé Marc 2026-07-31).

Revision ID: 0026_face_reference
Revises: 0025_instruction_position
Create Date: 2026-08-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026_face_reference"
down_revision: str | None = "0025_instruction_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "face_reference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_face_reference_account_id", "face_reference", ["account_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_face_reference_account_id", table_name="face_reference")
    op.drop_table("face_reference")
