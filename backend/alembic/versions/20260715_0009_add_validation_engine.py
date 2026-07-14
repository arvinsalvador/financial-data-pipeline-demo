# ruff: noqa: E501
"""add validation and data quality engine

Revision ID: a8d4c2e901f7
Revises: 8276076097a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d4c2e901f7"
down_revision: str | None = "8276076097a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validation_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("configuration_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_validation_rule_set_version"),
    )
    op.create_table(
        "validation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_rule_set_id", sa.Integer(), sa.ForeignKey("validation_rule_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rule_group", sa.String(60), nullable=False),
        sa.Column("target_entity", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("execution_order", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("validation_rule_set_id", "code", name="uq_validation_rule_code"),
        sa.UniqueConstraint("validation_rule_set_id", "execution_order", name="uq_validation_rule_order"),
    )
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("rule_set_id", sa.Integer(), sa.ForeignKey("validation_rule_sets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_version", sa.String(30), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.Integer()),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id", ondelete="SET NULL")),
        sa.Column("generated_dataset_run_id", sa.Integer(), sa.ForeignKey("generated_dataset_runs.id", ondelete="SET NULL")),
        sa.Column("messy_dataset_run_id", sa.Integer(), sa.ForeignKey("messy_dataset_runs.id", ondelete="SET NULL")),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("total_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disabled_rules", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_issues", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("information_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "rule_set_id", "target_type", "input_fingerprint", "validation_version", name="uq_validation_run_input"),
    )
    op.create_table(
        "validation_run_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_rule_id", sa.Integer(), sa.ForeignKey("validation_rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("records_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("details_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("validation_run_id", "validation_rule_id", name="uq_validation_result"),
    )
    op.create_table(
        "validation_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_rule_id", sa.Integer(), sa.ForeignKey("validation_rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_version", sa.String(30), nullable=False),
        sa.Column("issue_code", sa.String(120), nullable=False),
        sa.Column("issue_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_key", sa.String(255)),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id", ondelete="SET NULL")),
        sa.Column("filename", sa.String(255)),
        sa.Column("row_number", sa.Integer()),
        sa.Column("column_name", sa.String(120)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.Text()),
        sa.Column("expected_value", sa.Text()),
        sa.Column("issue_fingerprint", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("validation_run_id", "issue_fingerprint", name="uq_validation_issue"),
    )
    op.create_table(
        "validation_issue_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_issue_id", sa.Integer(), sa.ForeignKey("validation_issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "validation_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("validation_version", sa.String(30), nullable=False),
        sa.Column("overall_status", sa.String(30), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("counts_by_severity_json", sa.JSON(), nullable=False),
        sa.Column("counts_by_rule_json", sa.JSON(), nullable=False),
        sa.Column("counts_by_file_json", sa.JSON(), nullable=False),
        sa.Column("counts_by_entity_json", sa.JSON(), nullable=False),
        sa.Column("control_totals_json", sa.JSON(), nullable=False),
        sa.Column("summary_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "validation_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension_type", sa.String(50), nullable=False),
        sa.Column("dimension_key", sa.String(255), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("records_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("validation_run_id", "dimension_type", "dimension_key", name="uq_validation_statistic"),
    )
    op.create_table(
        "validation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), sa.ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("validation_version", sa.String(30), nullable=False),
        sa.Column("report_type", sa.String(60), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False, unique=True),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("validation_run_id", "report_type", name="uq_validation_report_type"),
    )
    for table, columns in {
        "validation_rule_sets": ("tenant_id", "code", "is_active"),
        "validation_rules": ("validation_rule_set_id", "code", "rule_group", "severity"),
        "validation_runs": ("tenant_id", "target_type", "status", "input_fingerprint"),
        "validation_run_results": ("validation_run_id", "validation_rule_id", "status"),
        "validation_issues": ("tenant_id", "validation_run_id", "validation_rule_id", "severity", "status", "entity_type", "filename", "issue_code"),
        "validation_statistics": ("validation_run_id", "dimension_type"),
        "validation_reports": ("validation_run_id", "report_type"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("validation_reports")
    op.drop_table("validation_statistics")
    op.drop_table("validation_summaries")
    op.drop_table("validation_issue_history")
    op.drop_table("validation_issues")
    op.drop_table("validation_run_results")
    op.drop_table("validation_runs")
    op.drop_table("validation_rules")
    op.drop_table("validation_rule_sets")
