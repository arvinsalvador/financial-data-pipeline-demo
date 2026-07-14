"""Create system_checks table.

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_checks_component", "system_checks", ["component"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_system_checks_component", table_name="system_checks")
    op.drop_table("system_checks")
