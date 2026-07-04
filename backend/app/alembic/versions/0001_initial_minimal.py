"""initial minimal backend schema

Revision ID: 0001_initial_minimal
Revises:
Create Date: 2026-04-01 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_initial_minimal"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Bootstrap an empty migration chain for the minimal template."""


def downgrade() -> None:
    """No application tables are created by the minimal template."""
