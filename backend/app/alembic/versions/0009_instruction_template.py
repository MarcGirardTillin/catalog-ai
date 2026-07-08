"""instruction_template (named editorial instruction library)

Revision ID: 0009_instruction_template
Revises: 0008_user_prefs_account_settings
Create Date: 2026-07-08 00:00:05.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_instruction_template"
down_revision: str | None = "0008_user_prefs_account_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruction_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("categories_json", sa.JSON(), nullable=True),
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
        op.f("ix_instruction_template_account_id"),
        "instruction_template",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_instruction_template_account_id"), table_name="instruction_template"
    )
    op.drop_table("instruction_template")
