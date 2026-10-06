"""Table api_token : jetons d'API personnels (serveur MCP).

Revision ID: 0028_api_token
Revises: 0027_common_usage_price
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028_api_token"
down_revision: str | None = "0027_common_usage_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_token_user_id", "api_token", ["user_id"])
    op.create_index("ix_api_token_token_hash", "api_token", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_token_token_hash", table_name="api_token")
    op.drop_index("ix_api_token_user_id", table_name="api_token")
    op.drop_table("api_token")
