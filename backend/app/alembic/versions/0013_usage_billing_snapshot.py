"""usage_billing_snapshot: frozen prices for billed (past) months

Revision ID: 0013_usage_billing_snapshot
Revises: 0012_usage_price
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_usage_billing_snapshot"
down_revision: str | None = "0012_usage_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_billing_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("coefficient", sa.Numeric(16, 6), nullable=False),
        sa.Column("prices_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_usage_billing_snapshot_account_id"),
        "usage_billing_snapshot",
        ["account_id"],
    )
    op.create_index(
        op.f("ix_usage_billing_snapshot_period"),
        "usage_billing_snapshot",
        ["period"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_usage_billing_snapshot_period"),
        table_name="usage_billing_snapshot",
    )
    op.drop_index(
        op.f("ix_usage_billing_snapshot_account_id"),
        table_name="usage_billing_snapshot",
    )
    op.drop_table("usage_billing_snapshot")
