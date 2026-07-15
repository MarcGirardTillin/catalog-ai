"""credit_entry: prepaid credit ledger (append-only, balance = SUM)

Revision ID: 0018_credit_entry
Revises: 0017_image_asset_staged_files
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_credit_entry"
down_revision: str | None = "0017_image_asset_staged_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=False
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("unit_credits", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("period", sa.String(length=7), nullable=True),
        sa.Column("price_eur", sa.Float(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_credit_entry_account_id", "credit_entry", ["account_id"])
    op.create_index(
        "ix_credit_entry_account_created",
        "credit_entry",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_credit_entry_account_created", table_name="credit_entry")
    op.drop_index("ix_credit_entry_account_id", table_name="credit_entry")
    op.drop_table("credit_entry")
