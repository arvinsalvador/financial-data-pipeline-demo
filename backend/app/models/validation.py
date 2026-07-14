from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ValidationRuleSet(Base):
    __tablename__ = "validation_rule_sets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_validation_rule_set_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    version: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationRule(Base):
    __tablename__ = "validation_rules"
    __table_args__ = (
        UniqueConstraint("validation_rule_set_id", "code", name="uq_validation_rule_code"),
        UniqueConstraint(
            "validation_rule_set_id", "execution_order", name="uq_validation_rule_order"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("validation_rule_sets.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text())
    rule_group: Mapped[str] = mapped_column(String(60), index=True)
    target_entity: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[str] = mapped_column(String(30))
    execution_order: Mapped[int] = mapped_column(Integer())
    is_enabled: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "rule_set_id",
            "target_type",
            "input_fingerprint",
            "validation_version",
            name="uq_validation_run_input",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), unique=True
    )
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("validation_rule_sets.id", ondelete="RESTRICT"), index=True
    )
    validation_version: Mapped[str] = mapped_column(String(30), index=True)
    target_type: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[int | None] = mapped_column(Integer(), index=True)
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"), index=True
    )
    generated_dataset_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="SET NULL"), index=True
    )
    messy_dataset_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("messy_dataset_runs.id", ondelete="SET NULL"), index=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    total_rules: Mapped[int] = mapped_column(Integer(), default=0)
    passed_rules: Mapped[int] = mapped_column(Integer(), default=0)
    failed_rules: Mapped[int] = mapped_column(Integer(), default=0)
    skipped_rules: Mapped[int] = mapped_column(Integer(), default=0)
    disabled_rules: Mapped[int] = mapped_column(Integer(), default=0)
    total_issues: Mapped[int] = mapped_column(Integer(), default=0)
    information_count: Mapped[int] = mapped_column(Integer(), default=0)
    warning_count: Mapped[int] = mapped_column(Integer(), default=0)
    error_count: Mapped[int] = mapped_column(Integer(), default=0)
    critical_count: Mapped[int] = mapped_column(Integer(), default=0)
    records_evaluated: Mapped[int] = mapped_column(Integer(), default=0)
    duration_ms: Mapped[int] = mapped_column(BigInteger(), default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationRunResult(Base):
    __tablename__ = "validation_run_results"
    __table_args__ = (
        UniqueConstraint("validation_run_id", "validation_rule_id", name="uq_validation_result"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True
    )
    validation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("validation_rules.id", ondelete="RESTRICT"), index=True
    )
    validation_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    records_evaluated: Mapped[int] = mapped_column(Integer(), default=0)
    issue_count: Mapped[int] = mapped_column(Integer(), default=0)
    duration_ms: Mapped[int] = mapped_column(BigInteger(), default=0)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    __table_args__ = (
        UniqueConstraint("validation_run_id", "issue_fingerprint", name="uq_validation_issue"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True
    )
    validation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("validation_rules.id", ondelete="RESTRICT"), index=True
    )
    validation_version: Mapped[str] = mapped_column(String(30), index=True)
    issue_code: Mapped[str] = mapped_column(String(120), index=True)
    issue_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_key: Mapped[str | None] = mapped_column(String(255), index=True)
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str | None] = mapped_column(String(255), index=True)
    row_number: Mapped[int | None] = mapped_column(Integer(), index=True)
    column_name: Mapped[str | None] = mapped_column(String(120), index=True)
    message: Mapped[str] = mapped_column(Text())
    observed_value: Mapped[str | None] = mapped_column(Text())
    expected_value: Mapped[str | None] = mapped_column(Text())
    issue_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ValidationIssueHistory(Base):
    __tablename__ = "validation_issue_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_issue_id: Mapped[int] = mapped_column(
        ForeignKey("validation_issues.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationSummary(Base):
    __tablename__ = "validation_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), unique=True
    )
    validation_version: Mapped[str] = mapped_column(String(30))
    overall_status: Mapped[str] = mapped_column(String(30), index=True)
    issue_count: Mapped[int] = mapped_column(Integer())
    counts_by_severity_json: Mapped[dict[str, int]] = mapped_column(JSON())
    counts_by_rule_json: Mapped[dict[str, int]] = mapped_column(JSON())
    counts_by_file_json: Mapped[dict[str, int]] = mapped_column(JSON())
    counts_by_entity_json: Mapped[dict[str, int]] = mapped_column(JSON())
    control_totals_json: Mapped[dict[str, Any]] = mapped_column(JSON())
    summary_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationStatistic(Base):
    __tablename__ = "validation_statistics"
    __table_args__ = (
        UniqueConstraint(
            "validation_run_id", "dimension_type", "dimension_key", name="uq_validation_statistic"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True
    )
    dimension_type: Mapped[str] = mapped_column(String(50), index=True)
    dimension_key: Mapped[str] = mapped_column(String(255), index=True)
    issue_count: Mapped[int] = mapped_column(Integer())
    records_evaluated: Mapped[int] = mapped_column(Integer(), default=0)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationReport(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (
        UniqueConstraint("validation_run_id", "report_type", name="uq_validation_report_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True
    )
    validation_version: Mapped[str] = mapped_column(String(30))
    report_type: Mapped[str] = mapped_column(String(60), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256_checksum: Mapped[str] = mapped_column(String(64), index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
