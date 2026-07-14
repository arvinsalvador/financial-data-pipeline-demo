from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceSchemaMapping(Base):
    __tablename__ = "source_schema_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "mapping_code", "mapping_version", name="uq_schema_mapping_version"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source_system_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_systems.id", ondelete="CASCADE"), index=True
    )
    source_file_pattern: Mapped[str] = mapped_column(String(255))
    mapping_code: Mapped[str] = mapped_column(String(100), index=True)
    mapping_name: Mapped[str] = mapped_column(String(255))
    mapping_version: Mapped[str] = mapped_column(String(30))
    target_record_type: Mapped[str] = mapped_column(String(50), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    required_columns_json: Mapped[list[str]] = mapped_column(JSON(), default=list)
    optional_columns_json: Mapped[list[str]] = mapped_column(JSON(), default=list)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    columns: Mapped[list["SourceSchemaMappingColumn"]] = relationship(
        cascade="all, delete-orphan", order_by="SourceSchemaMappingColumn.column_order"
    )


class SourceSchemaMappingColumn(Base):
    __tablename__ = "source_schema_mapping_columns"
    __table_args__ = (
        UniqueConstraint(
            "source_schema_mapping_id", "canonical_field_name", name="uq_mapping_canonical_field"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_schema_mapping_id: Mapped[int] = mapped_column(
        ForeignKey("source_schema_mappings.id", ondelete="CASCADE"), index=True
    )
    source_column_name: Mapped[str] = mapped_column(String(255))
    canonical_field_name: Mapped[str] = mapped_column(String(100))
    target_data_type: Mapped[str] = mapped_column(String(30))
    is_required: Mapped[bool] = mapped_column(Boolean(), default=False)
    parser_name: Mapped[str | None] = mapped_column(String(100))
    default_value_json: Mapped[Any | None] = mapped_column(JSON())
    transformation_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    column_order: Mapped[int] = mapped_column(Integer())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawSourceRow(Base):
    __tablename__ = "raw_source_rows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "ingestion_version",
            name="uq_raw_row_ingestion",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer())
    source_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    raw_data_json: Mapped[dict[str, str | None]] = mapped_column(JSON())
    raw_row_hash: Mapped[str] = mapped_column(String(64), index=True)
    ingestion_version: Mapped[str] = mapped_column(String(30))
    row_status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RejectedSourceRow(Base):
    __tablename__ = "rejected_source_rows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "raw_source_row_id", "rejection_fingerprint", name="uq_raw_row_rejection"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    raw_source_row_id: Mapped[int] = mapped_column(
        ForeignKey("raw_source_rows.id", ondelete="CASCADE"), index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer())
    rejection_code: Mapped[str] = mapped_column(String(100), index=True)
    rejection_category: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    field_name: Mapped[str | None] = mapped_column(String(255))
    observed_value: Mapped[str | None] = mapped_column(Text())
    message: Mapped[str] = mapped_column(Text())
    rejection_fingerprint: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionControlTotal(Base):
    __tablename__ = "ingestion_control_totals"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "control_name", name="uq_run_control_total"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    control_name: Mapped[str] = mapped_column(String(100), index=True)
    source_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    loaded_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    difference_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class _StagingBase:
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    raw_source_row_id: Mapped[int] = mapped_column(
        ForeignKey("raw_source_rows.id", ondelete="RESTRICT"), index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer())
    source_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    ingestion_version: Mapped[str] = mapped_column(String(30))
    row_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StagingBankTransaction(_StagingBase, Base):
    __tablename__ = "staging_bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "ingestion_version",
            name="uq_staging_bank_row",
        ),
    )
    account_source_code: Mapped[str | None] = mapped_column(String(255), index=True)
    transaction_date: Mapped[date] = mapped_column(Date(), index=True)
    posted_date: Mapped[date | None] = mapped_column(Date())
    description: Mapped[str | None] = mapped_column(Text())
    reference_number: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    debit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    running_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    counterparty_raw: Mapped[str | None] = mapped_column(Text())
    category_raw: Mapped[str | None] = mapped_column(Text())
    memo_raw: Mapped[str | None] = mapped_column(Text())


class StagingCreditCardTransaction(_StagingBase, Base):
    __tablename__ = "staging_credit_card_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "ingestion_version",
            name="uq_staging_card_row",
        ),
    )
    credit_account_source_code: Mapped[str | None] = mapped_column(String(255), index=True)
    transaction_date: Mapped[date] = mapped_column(Date(), index=True)
    posted_date: Mapped[date | None] = mapped_column(Date())
    description: Mapped[str | None] = mapped_column(Text())
    merchant_raw: Mapped[str | None] = mapped_column(Text())
    reference_number: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    debit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    category_raw: Mapped[str | None] = mapped_column(Text())
    currency: Mapped[str | None] = mapped_column(String(3))
    memo_raw: Mapped[str | None] = mapped_column(Text())


class StagingPayrollSummary(_StagingBase, Base):
    __tablename__ = "staging_payroll_summaries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "ingestion_version",
            name="uq_staging_payroll_summary_row",
        ),
    )
    payroll_run_source_id: Mapped[str | None] = mapped_column(String(255))
    pay_period_start: Mapped[date | None] = mapped_column(Date())
    pay_period_end: Mapped[date | None] = mapped_column(Date())
    pay_date: Mapped[date] = mapped_column(Date(), index=True)
    employee_source_id: Mapped[str] = mapped_column(String(255), index=True)
    employee_name_raw: Mapped[str | None] = mapped_column(Text())
    gross_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employee_deductions: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employer_contributions: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    reimbursements: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    net_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(3))


class StagingPayrollDetail(_StagingBase, Base):
    __tablename__ = "staging_payroll_details"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "ingestion_version",
            name="uq_staging_payroll_detail_row",
        ),
    )
    payroll_run_source_id: Mapped[str | None] = mapped_column(String(255))
    pay_period_start: Mapped[date | None] = mapped_column(Date())
    pay_period_end: Mapped[date | None] = mapped_column(Date())
    pay_date: Mapped[date] = mapped_column(Date(), index=True)
    employee_source_id: Mapped[str] = mapped_column(String(255), index=True)
    employee_name_raw: Mapped[str | None] = mapped_column(Text())
    earning_type_raw: Mapped[str | None] = mapped_column(Text())
    deduction_type_raw: Mapped[str | None] = mapped_column(Text())
    gross_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    regular_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    overtime_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    bonus_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    reimbursement_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employee_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employee_deduction: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employer_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employer_contribution: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    net_pay: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
