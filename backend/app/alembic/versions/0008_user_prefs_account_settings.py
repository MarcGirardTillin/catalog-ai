"""user.preferences_json + account.settings_json (settings page)

Revision ID: 0008_user_prefs_account_settings
Revises: 0007_item_apply_fields
Create Date: 2026-07-08 00:00:04.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_user_prefs_account_settings"
down_revision: str | None = "0007_item_apply_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("preferences_json", sa.JSON(), nullable=True))
    op.add_column("account", sa.Column("settings_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("account", "settings_json")
    op.drop_column("user", "preferences_json")
