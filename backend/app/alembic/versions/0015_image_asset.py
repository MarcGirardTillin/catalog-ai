"""image_asset: à-la-carte imaging operations (task tracking + trace + audit)

Revision ID: 0015_image_asset
Revises: 0014_import_item_tillin_link
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_image_asset"
down_revision: str | None = "0014_import_item_tillin_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("verb", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_image", sa.String(length=1000), nullable=True),
        sa.Column("source_product_image_id", sa.Integer(), nullable=True),
        sa.Column("staged_paths_json", sa.JSON(), nullable=False),
        sa.Column("tillin_image_ids_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_image_asset_product_id", "image_asset", ["product_id"])
    op.create_index("ix_image_asset_status", "image_asset", ["status"])


def downgrade() -> None:
    op.drop_index("ix_image_asset_status", table_name="image_asset")
    op.drop_index("ix_image_asset_product_id", table_name="image_asset")
    op.drop_table("image_asset")
