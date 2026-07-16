"""add payroll group reconciliation version

Revision ID: 76d9d3c52a31
Revises: 1bfe2a14f5f2
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "76d9d3c52a31"
down_revision: str | Sequence[str] | None = "1bfe2a14f5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payroll_reconciliation_groups",
        sa.Column(
            "reconciliation_version",
            sa.String(length=30),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.alter_column(
        "payroll_reconciliation_groups", "reconciliation_version", server_default=None
    )
    op.create_index(
        op.f("ix_payroll_reconciliation_groups_reconciliation_version"),
        "payroll_reconciliation_groups",
        ["reconciliation_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payroll_reconciliation_groups_reconciliation_version"),
        table_name="payroll_reconciliation_groups",
    )
    op.drop_column("payroll_reconciliation_groups", "reconciliation_version")
