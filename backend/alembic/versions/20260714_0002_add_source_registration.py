"""Add source registration and pipeline audit tables.

Revision ID: 20260714_0002
Revises: 20260714_0001
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0002"
down_revision: str | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_systems = op.create_table(
        "source_systems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_source_systems_code", "source_systems", ["code"], unique=True)
    op.create_index("ix_source_systems_source_type", "source_systems", ["source_type"])

    op.create_table(
        "source_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_system_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=330), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("file_extension", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"], ["source_systems.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("relative_path"),
        sa.UniqueConstraint("sha256_checksum"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index("ix_source_files_source_system_id", "source_files", ["source_system_id"])
    op.create_index("ix_source_files_sha256_checksum", "source_files", ["sha256_checksum"])
    op.create_index("ix_source_files_status", "source_files", ["status"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("records_extracted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_accepted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_rejected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_run_type", "pipeline_runs", ["run_type"])
    op.create_index("ix_pipeline_runs_source_file_id", "pipeline_runs", ["source_file_id"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])

    op.create_table(
        "pipeline_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=100), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_run_id", "step_order", name="uq_pipeline_run_step_order"),
    )
    op.create_index(
        "ix_pipeline_run_steps_pipeline_run_id", "pipeline_run_steps", ["pipeline_run_id"]
    )
    op.create_index("ix_pipeline_run_steps_status", "pipeline_run_steps", ["status"])
    op.create_index("ix_pipeline_run_steps_step_name", "pipeline_run_steps", ["step_name"])

    op.bulk_insert(
        source_systems,
        [
            {
                "code": "kaggle_small_business_finance",
                "name": "Kaggle Small Business Financial Dataset",
                "description": (
                    "Synthetic checking, credit-card, and payroll data used for the CFO "
                    "pipeline demo"
                ),
                "source_type": "csv",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_steps_step_name", table_name="pipeline_run_steps")
    op.drop_index("ix_pipeline_run_steps_status", table_name="pipeline_run_steps")
    op.drop_index("ix_pipeline_run_steps_pipeline_run_id", table_name="pipeline_run_steps")
    op.drop_table("pipeline_run_steps")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_source_file_id", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_run_type", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index("ix_source_files_status", table_name="source_files")
    op.drop_index("ix_source_files_sha256_checksum", table_name="source_files")
    op.drop_index("ix_source_files_source_system_id", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_source_systems_source_type", table_name="source_systems")
    op.drop_index("ix_source_systems_code", table_name="source_systems")
    op.drop_table("source_systems")
