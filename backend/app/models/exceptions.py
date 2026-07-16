from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnifiedException(Base):
    __tablename__ = "unified_exceptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "exception_key", name="uq_unified_exception_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    exception_key: Mapped[str] = mapped_column(String(64), index=True)
    source_module: Mapped[str] = mapped_column(String(80), index=True)
    source_exception_type: Mapped[str] = mapped_column(String(100), index=True)
    source_exception_id: Mapped[str] = mapped_column(String(100), index=True)
    exception_code: Mapped[str] = mapped_column(String(120), index=True)
    exception_category: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text())
    severity: Mapped[str] = mapped_column(String(20), index=True)
    priority: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    workflow_state: Mapped[str] = mapped_column(String(40), index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_team_code: Mapped[str | None] = mapped_column(String(80), index=True)
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"), index=True
    )
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(100), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer(), index=True)
    field_name: Mapped[str | None] = mapped_column(String(255), index=True)
    observed_value_summary: Mapped[str | None] = mapped_column(Text())
    expected_value_summary: Mapped[str | None] = mapped_column(Text())
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    suggested_action: Mapped[str | None] = mapped_column(String(255))
    resolution_code: Mapped[str | None] = mapped_column(String(120), index=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text())
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer(), default=1)
    unified_exception_version: Mapped[str] = mapped_column(String(30), index=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    synchronization_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source_resolved: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UnifiedExceptionSource(Base):
    __tablename__ = "unified_exception_sources"
    __table_args__ = (
        UniqueConstraint(
            "unified_exception_id",
            "source_module",
            "source_entity_type",
            "source_entity_id",
            "source_exception_id",
            "relationship_type",
            name="uq_unified_exception_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    source_module: Mapped[str] = mapped_column(String(80), index=True)
    source_entity_type: Mapped[str] = mapped_column(String(100), index=True)
    source_entity_id: Mapped[str] = mapped_column(String(100), index=True)
    source_exception_id: Mapped[str] = mapped_column(String(100), index=True)
    relationship_type: Mapped[str] = mapped_column(String(50), index=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiedExceptionAssignment(Base):
    __tablename__ = "unified_exception_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_team_code: Mapped[str | None] = mapped_column(String(80), index=True)
    assignment_type: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiedExceptionComment(Base):
    __tablename__ = "unified_exception_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    comment_type: Mapped[str] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(Text())
    is_internal: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnifiedExceptionDecision(Base):
    __tablename__ = "unified_exception_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    decision_type: Mapped[str] = mapped_column(String(50), index=True)
    previous_status: Mapped[str] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    resolution_code: Mapped[str | None] = mapped_column(String(120), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(String(1000))
    source_decision_id: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiedExceptionStatusHistory(Base):
    __tablename__ = "unified_exception_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("unified_exception_decisions.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiedExceptionRelation(Base):
    __tablename__ = "unified_exception_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_unified_exception_id",
            "target_unified_exception_id",
            "relation_type",
            name="uq_unified_exception_relation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    source_unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    target_unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(50), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiedExceptionEvidence(Base):
    __tablename__ = "unified_exception_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str] = mapped_column(String(255))
    source_entity_type: Mapped[str | None] = mapped_column(String(100))
    source_entity_id: Mapped[str | None] = mapped_column(String(100))
    relative_path: Mapped[str | None] = mapped_column(String(500))
    checksum: Mapped[str | None] = mapped_column(String(64))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    added_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExceptionWorkflowRule(Base):
    __tablename__ = "exception_workflow_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_exception_workflow_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    source_module: Mapped[str | None] = mapped_column(String(80), index=True)
    exception_code_pattern: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str | None] = mapped_column(String(20), index=True)
    initial_priority: Mapped[str] = mapped_column(String(20))
    initial_status: Mapped[str] = mapped_column(String(40))
    auto_assign_team_code: Mapped[str | None] = mapped_column(String(80))
    auto_assign_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    escalation_after_hours: Mapped[int | None] = mapped_column(Integer())
    resolution_requires_comment: Mapped[bool] = mapped_column(Boolean(), default=True)
    ignore_requires_comment: Mapped[bool] = mapped_column(Boolean(), default=True)
    reopen_on_redetection: Mapped[bool] = mapped_column(Boolean(), default=True)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    version: Mapped[str] = mapped_column(String(30))
    execution_order: Mapped[int] = mapped_column(Integer(), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExceptionServiceLevelPolicy(Base):
    __tablename__ = "exception_service_level_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_exception_sla_policy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    response_hours: Mapped[int] = mapped_column(Integer())
    resolution_hours: Mapped[int] = mapped_column(Integer())
    escalation_hours: Mapped[int] = mapped_column(Integer())
    business_hours_only: Mapped[bool] = mapped_column(Boolean(), default=False)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExceptionResolutionCode(Base):
    __tablename__ = "exception_resolution_codes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_exception_resolution_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExceptionSavedView(Base):
    __tablename__ = "exception_saved_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text())
    is_shared: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    filter_json: Mapped[dict[str, Any]] = mapped_column(JSONB())
    sort_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    column_json: Mapped[list[str] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExceptionNotificationEvent(Base):
    __tablename__ = "exception_notification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    unified_exception_id: Mapped[int] = mapped_column(
        ForeignKey("unified_exceptions.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(60), index=True)
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    recipient_team_code: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExceptionManagementRun(Base):
    __tablename__ = "exception_management_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    run_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    source_modules_json: Mapped[list[str]] = mapped_column(JSONB())
    scanned_count: Mapped[int] = mapped_column(Integer(), default=0)
    created_count: Mapped[int] = mapped_column(Integer(), default=0)
    updated_count: Mapped[int] = mapped_column(Integer(), default=0)
    reopened_count: Mapped[int] = mapped_column(Integer(), default=0)
    skipped_count: Mapped[int] = mapped_column(Integer(), default=0)
    failed_count: Mapped[int] = mapped_column(Integer(), default=0)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExceptionManagementReport(Base):
    __tablename__ = "exception_management_reports"
    __table_args__ = (
        UniqueConstraint("exception_management_run_id", "report_type", name="uq_exception_report"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    exception_management_run_id: Mapped[int] = mapped_column(
        ForeignKey("exception_management_runs.id", ondelete="CASCADE"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(80), index=True)
    relative_path: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
