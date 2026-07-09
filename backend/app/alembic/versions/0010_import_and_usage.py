"""import jobs (job_type + import_item) and usage metering (usage_event)

Revision ID: 0010_import_and_usage
Revises: 0009_instruction_template
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_import_and_usage"
down_revision: str | None = "0009_instruction_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrichment_job",
        sa.Column(
            "job_type",
            sa.String(length=20),
            nullable=False,
            server_default="enrichment",
        ),
    )

    op.create_table(
        "import_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["job_id"], ["enrichment_job.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_item_job_id"), "import_item", ["job_id"])
    op.create_index(op.f("ix_import_item_account_id"), "import_item", ["account_id"])

    op.create_table(
        "usage_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("metric", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["enrichment_job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usage_event_account_id"), "usage_event", ["account_id"])
    op.create_index(op.f("ix_usage_event_job_id"), "usage_event", ["job_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_event_job_id"), table_name="usage_event")
    op.drop_index(op.f("ix_usage_event_account_id"), table_name="usage_event")
    op.drop_table("usage_event")
    op.drop_index(op.f("ix_import_item_account_id"), table_name="import_item")
    op.drop_index(op.f("ix_import_item_job_id"), table_name="import_item")
    op.drop_table("import_item")
    op.drop_column("enrichment_job", "job_type")
