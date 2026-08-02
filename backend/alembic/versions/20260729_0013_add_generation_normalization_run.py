"""Link generated datasets to their eligible normalization snapshot.

Revision ID: 20260729_0013
Revises: 20260717_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260729_0013"
down_revision: str | None = "20260717_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_dataset_runs",
        sa.Column("normalization_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_generated_dataset_normalization_run",
        "generated_dataset_runs",
        "pipeline_runs",
        ["normalization_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_generated_dataset_runs_normalization_run_id",
        "generated_dataset_runs",
        ["normalization_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generated_dataset_runs_normalization_run_id",
        table_name="generated_dataset_runs",
    )
    op.drop_constraint(
        "fk_generated_dataset_normalization_run",
        "generated_dataset_runs",
        type_="foreignkey",
    )
    op.drop_column("generated_dataset_runs", "normalization_run_id")
