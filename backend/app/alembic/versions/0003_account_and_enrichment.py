"""account + enrichment tables, backfill user.account_id

Revision ID: 0003_account_and_enrichment
Revises: 0002_add_user
Create Date: 2026-07-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_account_and_enrichment"
down_revision: str | None = "0002_add_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Single-tenant default account; everything is scoped to it for now.
    op.execute("INSERT INTO account (name) VALUES ('default')")

    op.add_column("user", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_user_account_id", "user", "account", ["account_id"], ["id"]
    )
    op.create_index(op.f("ix_user_account_id"), "user", ["account_id"])
    op.execute(
        "UPDATE \"user\" SET account_id = (SELECT id FROM account WHERE name = 'default')"
    )

    op.create_table(
        "enrichment_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("selection_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_enrichment_job_account_id"), "enrichment_job", ["account_id"]
    )
    op.create_index(op.f("ix_enrichment_job_status"), "enrichment_job", ["status"])

    op.create_table(
        "enrichment_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("tillin_product_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("source_method", sa.String(length=30), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("staged_title", sa.String(length=500), nullable=True),
        sa.Column("staged_description", sa.String(), nullable=True),
        sa.Column("staged_meta", sa.String(length=500), nullable=True),
        sa.Column("staged_images_json", sa.JSON(), nullable=True),
        sa.Column("staged_weights_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["job_id"], ["enrichment_job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_enrichment_item_account_id"), "enrichment_item", ["account_id"]
    )
    op.create_index(op.f("ix_enrichment_item_job_id"), "enrichment_item", ["job_id"])
    op.create_index(
        "ix_enrichment_item_status_id", "enrichment_item", ["status", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_enrichment_item_status_id", table_name="enrichment_item")
    op.drop_index(op.f("ix_enrichment_item_job_id"), table_name="enrichment_item")
    op.drop_index(op.f("ix_enrichment_item_account_id"), table_name="enrichment_item")
    op.drop_table("enrichment_item")
    op.drop_index(op.f("ix_enrichment_job_status"), table_name="enrichment_job")
    op.drop_index(op.f("ix_enrichment_job_account_id"), table_name="enrichment_job")
    op.drop_table("enrichment_job")
    op.drop_index(op.f("ix_user_account_id"), table_name="user")
    op.drop_constraint("fk_user_account_id", "user", type_="foreignkey")
    op.drop_column("user", "account_id")
    op.drop_table("account")
