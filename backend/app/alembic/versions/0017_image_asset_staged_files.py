"""image_asset.staged_files_json: staged files metadata (role/bytes/dims)

Additive: `staged_paths_json` keeps carrying the ordered OUTPUT paths (the
preview/save/batch flows read it unchanged); the new column adds one entry per
staged file — role source|cutout|output, path, bytes, width, height, format,
index. NULL on legacy assets (pre-migration): readers fall back to
staged_paths_json.

Revision ID: 0017_image_asset_staged_files
Revises: 0016_user_is_admin
Create Date: 2026-07-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_image_asset_staged_files"
down_revision: str | None = "0016_user_is_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_asset",
        sa.Column("staged_files_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("image_asset", "staged_files_json")
