"""add unified exception management

Revision ID: 20260717_0012
Revises: adc0bcae911e
Create Date: 2026-07-17 08:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260717_0012"
down_revision = "adc0bcae911e"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "unified_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exception_key", sa.String(64), nullable=False),
        sa.Column("source_module", sa.String(80), nullable=False),
        sa.Column("source_exception_type", sa.String(100), nullable=False),
        sa.Column("source_exception_id", sa.String(100), nullable=False),
        sa.Column("exception_code", sa.String(120), nullable=False),
        sa.Column("exception_category", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("workflow_state", sa.String(40), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_team_code", sa.String(80)),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id", ondelete="SET NULL")),
        sa.Column("pipeline_run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL")),
        sa.Column("entity_type", sa.String(100)),
        sa.Column("entity_id", sa.String(255)),
        sa.Column("source_row_number", sa.Integer()),
        sa.Column("field_name", sa.String(255)),
        sa.Column("observed_value_summary", sa.Text()),
        sa.Column("expected_value_summary", sa.Text()),
        sa.Column("confidence", sa.Numeric(8, 6)),
        sa.Column("suggested_action", sa.String(255)),
        sa.Column("resolution_code", sa.String(120)),
        sa.Column("resolution_summary", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("ignored_at", sa.DateTime(timezone=True)),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unified_exception_version", sa.String(30), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("synchronization_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", jsonb),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "exception_key", name="uq_unified_exception_key"),
    )
    for column in ("tenant_id", "status", "severity", "priority", "assigned_user_id", "assigned_team_code", "due_at", "source_module", "exception_code", "exception_key", "synchronization_fingerprint", "first_detected_at", "last_detected_at"):
        op.create_index(f"ix_unified_exceptions_{column}", "unified_exceptions", [column])

    op.create_table(
        "unified_exception_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_module", sa.String(80), nullable=False, index=True),
        sa.Column("source_entity_type", sa.String(100), nullable=False, index=True),
        sa.Column("source_entity_id", sa.String(100), nullable=False, index=True),
        sa.Column("source_exception_id", sa.String(100), nullable=False, index=True),
        sa.Column("relationship_type", sa.String(50), nullable=False, index=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("metadata_json", jsonb),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("unified_exception_id", "source_module", "source_entity_type", "source_entity_id", "source_exception_id", "relationship_type", name="uq_unified_exception_source"),
    )

    op.create_table(
        "unified_exception_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("assigned_team_code", sa.String(80), index=True),
        sa.Column("assignment_type", sa.String(40), nullable=False, index=True),
        sa.Column("reason", sa.String(500)),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "unified_exception_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("comment_type", sa.String(40), nullable=False, index=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("metadata_json", jsonb),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "unified_exception_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("decision_type", sa.String(50), nullable=False, index=True),
        sa.Column("previous_status", sa.String(40), nullable=False),
        sa.Column("new_status", sa.String(40), nullable=False),
        sa.Column("resolution_code", sa.String(120), index=True),
        sa.Column("reason", sa.String(500)),
        sa.Column("notes", sa.String(1000)),
        sa.Column("source_decision_id", sa.String(100)),
        sa.Column("metadata_json", jsonb),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "unified_exception_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40), nullable=False, index=True),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("unified_exception_decisions.id", ondelete="SET NULL"), index=True),
        sa.Column("reason", sa.String(500)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "unified_exception_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("source_unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relation_type", sa.String(50), nullable=False, index=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_unified_exception_id", "target_unified_exception_id", "relation_type", name="uq_unified_exception_relation"),
        sa.CheckConstraint("source_unified_exception_id <> target_unified_exception_id", name="ck_unified_exception_relation_not_self"),
    )
    op.create_table(
        "unified_exception_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_type", sa.String(60), nullable=False, index=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("source_entity_type", sa.String(100)),
        sa.Column("source_entity_id", sa.String(100)),
        sa.Column("relative_path", sa.String(500)),
        sa.Column("checksum", sa.String(64)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("metadata_json", jsonb),
        sa.Column("added_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "exception_workflow_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(120), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source_module", sa.String(80), index=True),
        sa.Column("exception_code_pattern", sa.String(255)),
        sa.Column("severity", sa.String(20), index=True),
        sa.Column("initial_priority", sa.String(20), nullable=False),
        sa.Column("initial_status", sa.String(40), nullable=False),
        sa.Column("auto_assign_team_code", sa.String(80)),
        sa.Column("auto_assign_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("escalation_after_hours", sa.Integer()),
        sa.Column("resolution_requires_comment", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ignore_requires_comment", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reopen_on_redetection", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("configuration_json", jsonb),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("execution_order", sa.Integer(), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_exception_workflow_rule"),
    )
    op.create_table(
        "exception_service_level_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(80), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("response_hours", sa.Integer(), nullable=False),
        sa.Column("resolution_hours", sa.Integer(), nullable=False),
        sa.Column("escalation_hours", sa.Integer(), nullable=False),
        sa.Column("business_hours_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("configuration_json", jsonb),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_exception_sla_policy"),
    )
    op.create_table(
        "exception_resolution_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(120), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_exception_resolution_code"),
    )
    op.create_table(
        "exception_saved_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("filter_json", jsonb, nullable=False),
        sa.Column("sort_json", jsonb),
        sa.Column("column_json", jsonb),
        *_timestamps(),
    )
    op.create_table(
        "exception_notification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("unified_exception_id", sa.Integer(), sa.ForeignKey("unified_exceptions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("notification_type", sa.String(60), nullable=False, index=True),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("recipient_team_code", sa.String(80), index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("payload_json", jsonb),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "exception_management_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("pipeline_run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True),
        sa.Column("run_type", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(40), nullable=False, index=True),
        sa.Column("source_modules_json", jsonb, nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reopened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_fingerprint", sa.String(64), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", jsonb),
        *_timestamps(),
    )
    op.create_table(
        "exception_management_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("exception_management_run_id", sa.Integer(), sa.ForeignKey("exception_management_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("report_type", sa.String(80), nullable=False, index=True),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", jsonb),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("exception_management_run_id", "report_type", name="uq_exception_report"),
    )


def downgrade() -> None:
    for table in (
        "exception_management_reports",
        "exception_management_runs",
        "exception_notification_events",
        "exception_saved_views",
        "exception_resolution_codes",
        "exception_service_level_policies",
        "exception_workflow_rules",
        "unified_exception_evidence",
        "unified_exception_relations",
        "unified_exception_status_history",
        "unified_exception_decisions",
        "unified_exception_comments",
        "unified_exception_assignments",
        "unified_exception_sources",
        "unified_exceptions",
    ):
        op.drop_table(table)
