"""multi-tenant: account.xano_company_id + user Xano token capture

One CatalogAI account per Tillin company; catalog calls carry the user's own
Xano token (company-scoped by Xano) instead of a shared service identity.

Revision ID: 0019_multi_tenant_tokens
Revises: 0018_credit_entry
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019_multi_tenant_tokens"
down_revision: str | None = "0018_credit_entry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("account", sa.Column("xano_company_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_account_xano_company_id",
        "account",
        ["xano_company_id"],
        unique=True,
    )
    # Xano tokens are opaque JWE strings (~700 chars today): Text, not String.
    op.add_column("user", sa.Column("xano_token", sa.Text(), nullable=True))
    op.add_column(
        "user", sa.Column("xano_token_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user", "xano_token_at")
    op.drop_column("user", "xano_token")
    op.drop_index("ix_account_xano_company_id", table_name="account")
    op.drop_column("account", "xano_company_id")
