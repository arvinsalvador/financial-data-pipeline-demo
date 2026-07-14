"""Add CSV profiling and data-quality tables.

Revision ID: 20260714_0003
Revises: 20260714_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0003"
down_revision: str | None = "20260714_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "source_file_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("encoding", sa.String(length=50)),
        sa.Column("delimiter", sa.String(length=10)),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("column_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("empty_row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("date_range_start", sa.Date()),
        sa.Column("date_range_end", sa.Date()),
        sa.Column("total_null_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_non_null_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_numeric_columns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_date_columns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_text_columns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_boolean_columns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("monetary_total", sa.Numeric(24, 6)),
        sa.Column("debit_total", sa.Numeric(24, 6)),
        sa.Column("credit_total", sa.Numeric(24, 6)),
        sa.Column("opening_balance", sa.Numeric(24, 6)),
        sa.Column("closing_balance", sa.Numeric(24, 6)),
        sa.Column("calculated_closing_balance", sa.Numeric(24, 6)),
        sa.Column("running_balance_valid", sa.Boolean()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.Column("profile_metadata_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_id", "profile_version", name="uq_source_file_profile_version"),
    )
    for column in ("source_file_id", "pipeline_run_id", "status"):
        op.create_index(f"ix_source_file_profiles_{column}", "source_file_profiles", [column])

    op.create_table(
        "source_file_column_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_file_profile_id", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=False),
        sa.Column("column_position", sa.Integer(), nullable=False),
        sa.Column("inferred_data_type", sa.String(length=30), nullable=False),
        sa.Column("original_data_type", sa.String(length=30), server_default="string", nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("null_count", sa.Integer(), nullable=False),
        sa.Column("non_null_count", sa.Integer(), nullable=False),
        sa.Column("null_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("unique_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_value_count", sa.Integer(), nullable=False),
        sa.Column("minimum_value", sa.String(length=500)),
        sa.Column("maximum_value", sa.String(length=500)),
        sa.Column("mean_value", sa.Numeric(24, 6)),
        sa.Column("median_value", sa.Numeric(24, 6)),
        sa.Column("standard_deviation", sa.Numeric(24, 6)),
        sa.Column("minimum_length", sa.Integer()),
        sa.Column("maximum_length", sa.Integer()),
        sa.Column("average_length", sa.Numeric(12, 4)),
        sa.Column("earliest_date", sa.Date()),
        sa.Column("latest_date", sa.Date()),
        sa.Column("sample_values_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("detected_formats_json", postgresql.JSONB(astext_type=sa.Text())),
        *timestamps(),
        sa.ForeignKeyConstraint(["source_file_profile_id"], ["source_file_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_profile_id", "column_position", name="uq_column_profile_position"),
    )
    op.create_index("ix_source_file_column_profiles_source_file_profile_id", "source_file_column_profiles", ["source_file_profile_id"])
    op.create_index("ix_source_file_column_profiles_inferred_data_type", "source_file_column_profiles", ["inferred_data_type"])

    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("source_file_profile_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(length=255)),
        sa.Column("row_number", sa.Integer()),
        sa.Column("issue_code", sa.String(length=100), nullable=False),
        sa.Column("issue_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.Text()),
        sa.Column("expected_value", sa.Text()),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("issue_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_profile_id"], ["source_file_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_fingerprint"),
    )
    for column in ("source_file_id", "source_file_profile_id", "pipeline_run_id", "column_name", "issue_code", "issue_type", "severity", "status", "issue_fingerprint"):
        op.create_index(f"ix_data_quality_issues_{column}", "data_quality_issues", [column], unique=column == "issue_fingerprint")


def downgrade() -> None:
    op.drop_table("data_quality_issues")
    op.drop_table("source_file_column_profiles")
    op.drop_table("source_file_profiles")
