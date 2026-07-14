from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DefectScenario(Base):
    __tablename__ = "defect_scenarios"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_defect_scenario_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    version: Mapped[str] = mapped_column(String(30))
    is_system_scenario: Mapped[bool] = mapped_column(Boolean(), default=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DefectScenarioRule(Base):
    __tablename__ = "defect_scenario_rules"
    __table_args__ = (
        UniqueConstraint("defect_scenario_id", "rule_code", name="uq_defect_scenario_rule"),
        UniqueConstraint("defect_scenario_id", "rule_order", name="uq_defect_scenario_rule_order"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    defect_scenario_id: Mapped[int] = mapped_column(
        ForeignKey("defect_scenarios.id", ondelete="CASCADE"), index=True
    )
    rule_code: Mapped[str] = mapped_column(String(120), index=True)
    defect_type: Mapped[str] = mapped_column(String(100), index=True)
    target_file_type: Mapped[str] = mapped_column(String(100), index=True)
    target_column: Mapped[str | None] = mapped_column(String(120))
    requested_count: Mapped[int | None] = mapped_column(Integer())
    requested_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    severity: Mapped[str] = mapped_column(String(30), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    rule_order: Mapped[int] = mapped_column(Integer())
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MessyDatasetRun(Base):
    __tablename__ = "messy_dataset_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "clean_generated_dataset_run_id",
            "defect_scenario_id",
            "random_seed",
            "input_fingerprint",
            "defect_plan_fingerprint",
            name="uq_messy_dataset_inputs",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), unique=True
    )
    clean_generated_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="RESTRICT"), index=True
    )
    defect_scenario_id: Mapped[int] = mapped_column(
        ForeignKey("defect_scenarios.id", ondelete="RESTRICT"), index=True
    )
    messy_generator_version: Mapped[str] = mapped_column(String(30))
    random_seed: Mapped[int] = mapped_column(Integer())
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    defect_plan_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    output_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clean_file_count: Mapped[int] = mapped_column(Integer(), default=0)
    messy_file_count: Mapped[int] = mapped_column(Integer(), default=0)
    requested_defect_count: Mapped[int] = mapped_column(Integer(), default=0)
    applied_defect_count: Mapped[int] = mapped_column(Integer(), default=0)
    skipped_defect_count: Mapped[int] = mapped_column(Integer(), default=0)
    failed_defect_count: Mapped[int] = mapped_column(Integer(), default=0)
    expected_exception_count: Mapped[int] = mapped_column(Integer(), default=0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MessySourceFile(Base):
    __tablename__ = "messy_source_files"
    __table_args__ = (
        UniqueConstraint("messy_dataset_run_id", "file_type", name="uq_messy_file_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    messy_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("messy_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    clean_generated_source_file_id: Mapped[int] = mapped_column(
        ForeignKey("generated_source_files.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    file_type: Mapped[str] = mapped_column(String(100), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256_checksum: Mapped[str] = mapped_column(String(64), index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    row_count: Mapped[int] = mapped_column(Integer())
    column_count: Mapped[int] = mapped_column(Integer())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataMutation(Base):
    __tablename__ = "data_mutations"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    messy_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("messy_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    source_clean_file_id: Mapped[int] = mapped_column(
        ForeignKey("generated_source_files.id", ondelete="RESTRICT"), index=True
    )
    source_messy_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("messy_source_files.id", ondelete="SET NULL"), index=True
    )
    defect_scenario_rule_id: Mapped[int] = mapped_column(
        ForeignKey("defect_scenario_rules.id", ondelete="RESTRICT"), index=True
    )
    defect_type: Mapped[str] = mapped_column(String(100), index=True)
    target_file_type: Mapped[str] = mapped_column(String(100), index=True)
    target_filename: Mapped[str] = mapped_column(String(255), index=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer(), index=True)
    source_record_key: Mapped[str | None] = mapped_column(String(255), index=True)
    target_column: Mapped[str | None] = mapped_column(String(120), index=True)
    original_value: Mapped[str | None] = mapped_column(Text())
    mutated_value: Mapped[str | None] = mapped_column(Text())
    mutation_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mutation_status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpectedException(Base):
    __tablename__ = "expected_exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    messy_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("messy_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    expected_exception_code: Mapped[str] = mapped_column(String(120), index=True)
    expected_issue_type: Mapped[str] = mapped_column(String(100), index=True)
    expected_severity: Mapped[str] = mapped_column(String(30), index=True)
    expected_file_type: Mapped[str] = mapped_column(String(100), index=True)
    expected_filename: Mapped[str] = mapped_column(String(255), index=True)
    expected_source_row_number: Mapped[int | None] = mapped_column(Integer(), index=True)
    expected_source_record_key: Mapped[str | None] = mapped_column(String(255), index=True)
    expected_column_name: Mapped[str | None] = mapped_column(String(120), index=True)
    related_mutation_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_mutations.id", ondelete="SET NULL"), index=True
    )
    expected_message_pattern: Mapped[str] = mapped_column(String(500))
    expected_count_group: Mapped[str | None] = mapped_column(String(120))
    expectation_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MessyGenerationControlTotal(Base):
    __tablename__ = "messy_generation_control_totals"
    __table_args__ = (
        UniqueConstraint("messy_dataset_run_id", "control_name", name="uq_messy_control"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    messy_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("messy_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    control_name: Mapped[str] = mapped_column(String(120), index=True)
    clean_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    messy_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    difference_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    expected_difference: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    tolerance: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
