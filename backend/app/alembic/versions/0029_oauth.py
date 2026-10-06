"""Tables OAuth du serveur MCP : oauth_client, oauth_authorization, oauth_token.

Revision ID: 0029_oauth
Revises: 0028_api_token
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029_oauth"
down_revision: str | None = "0028_api_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "oauth_client",
        sa.Column("client_id", sa.String(length=64), primary_key=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        _created_at(),
    )
    op.create_table(
        "oauth_authorization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("oauth_client.client_id"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_explicit", sa.Boolean(), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_index(
        "ix_oauth_authorization_request_key",
        "oauth_authorization",
        ["request_key"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_authorization_code_hash",
        "oauth_authorization",
        ["code_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_authorization_client_id", "oauth_authorization", ["client_id"]
    )
    op.create_table(
        "oauth_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("oauth_client.client_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_index(
        "ix_oauth_token_token_hash", "oauth_token", ["token_hash"], unique=True
    )
    op.create_index("ix_oauth_token_family", "oauth_token", ["family"])
    op.create_index("ix_oauth_token_client_id", "oauth_token", ["client_id"])
    op.create_index("ix_oauth_token_user_id", "oauth_token", ["user_id"])


def downgrade() -> None:
    for name in (
        "ix_oauth_token_user_id",
        "ix_oauth_token_client_id",
        "ix_oauth_token_family",
        "ix_oauth_token_token_hash",
    ):
        op.drop_index(name, table_name="oauth_token")
    op.drop_table("oauth_token")
    for name in (
        "ix_oauth_authorization_client_id",
        "ix_oauth_authorization_code_hash",
        "ix_oauth_authorization_request_key",
    ):
        op.drop_index(name, table_name="oauth_authorization")
    op.drop_table("oauth_authorization")
    op.drop_table("oauth_client")
