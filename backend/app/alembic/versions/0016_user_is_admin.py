"""user.is_admin: platform-operator role (admin console, white-label gating)

Promotes marc.girard@tillin.fr (the platform operator) in the same migration —
no-op when the row does not exist yet (fresh databases: promote manually).

Revision ID: 0016_user_is_admin
Revises: 0015_image_asset
Create Date: 2026-07-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_user_is_admin"
down_revision: str | None = "0015_image_asset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPERATOR_EMAIL = "marc.girard@tillin.fr"


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text('UPDATE "user" SET is_admin = TRUE WHERE email = :email').bindparams(
            email=OPERATOR_EMAIL
        )
    )


def downgrade() -> None:
    op.drop_column("user", "is_admin")
