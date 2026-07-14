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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Currency(Base):
    __tablename__ = "currencies"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(3), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(10))
    decimal_places: Mapped[int] = mapped_column(Integer(), default=2)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FinancialAccount(Base):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_code", name="uq_financial_account_code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    account_code: Mapped[str] = mapped_column(String(50), index=True)
    account_name: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(30), index=True)
    account_subtype: Mapped[str | None] = mapped_column(String(50))
    normal_balance: Mapped[str] = mapped_column(String(10))
    parent_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT")
    )
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    is_system_generated: Mapped[bool] = mapped_column(Boolean(), default=True)
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_system_id", "source_account_code", name="uq_bank_source_account"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    financial_account_id: Mapped[int] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_account_code: Mapped[str] = mapped_column(String(100))
    account_name: Mapped[str] = mapped_column(String(255))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    masked_account_number: Mapped[str | None] = mapped_column(String(50))
    account_type: Mapped[str] = mapped_column(String(30))
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_system_id", "source_account_code", name="uq_credit_source_account"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    financial_account_id: Mapped[int] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_account_code: Mapped[str] = mapped_column(String(100))
    account_name: Mapped[str] = mapped_column(String(255))
    issuer_name: Mapped[str | None] = mapped_column(String(255))
    masked_account_number: Mapped[str | None] = mapped_column(String(50))
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Counterparty(Base):
    __tablename__ = "counterparties"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "counterparty_type", "normalized_name", name="uq_counterparty_normalized"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    counterparty_type: Mapped[str] = mapped_column(String(30), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor_code", name="uq_vendor_code"),
        UniqueConstraint("tenant_id", "counterparty_id", name="uq_vendor_counterparty"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT")
    )
    vendor_code: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer())
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_code", name="uq_customer_code"),
        UniqueConstraint("tenant_id", "counterparty_id", name="uq_customer_counterparty"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT")
    )
    customer_code: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer())
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_system_id", "employee_source_id", name="uq_employee_source"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT")
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    employee_source_id: Mapped[str] = mapped_column(String(255), index=True)
    employee_number: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30))
    hire_date: Mapped[date | None] = mapped_column(Date())
    termination_date: Mapped[date | None] = mapped_column(Date())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransactionCategory(Base):
    __tablename__ = "transaction_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_transaction_category_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category_type: Mapped[str] = mapped_column(String(30))
    parent_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction_categories.id", ondelete="RESTRICT")
    )
    financial_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_accounts.id", ondelete="RESTRICT")
    )
    is_system_category: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FinancialTransaction(Base):
    __tablename__ = "financial_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file_id",
            "source_row_number",
            "normalization_version",
            name="uq_canonical_transaction_source",
        ),
        UniqueConstraint("tenant_id", "canonical_hash", name="uq_canonical_transaction_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(30), index=True)
    transaction_date: Mapped[date] = mapped_column(Date(), index=True)
    posted_date: Mapped[date | None] = mapped_column(Date())
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text())
    normalized_description: Mapped[str | None] = mapped_column(Text())
    reference_number: Mapped[str | None] = mapped_column(String(255))
    counterparty_id: Mapped[int | None] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("transaction_categories.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT")
    )
    normalization_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    source_row_number: Mapped[int] = mapped_column(Integer())
    normalization_version: Mapped[str] = mapped_column(String(30))
    canonical_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "staging_bank_transaction_id",
            "normalization_version",
            name="uq_bank_normalized_staging",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    financial_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("financial_transactions.id", ondelete="CASCADE"), unique=True
    )
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), index=True
    )
    staging_bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("staging_bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    debit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    running_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    transaction_direction: Mapped[str] = mapped_column(String(20))
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean(), default=False)
    normalization_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditCardTransaction(Base):
    __tablename__ = "credit_card_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "staging_credit_card_transaction_id",
            "normalization_version",
            name="uq_card_normalized_staging",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    financial_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("financial_transactions.id", ondelete="CASCADE"), unique=True
    )
    credit_account_id: Mapped[int] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="RESTRICT"), index=True
    )
    staging_credit_card_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("staging_credit_card_transactions.id", ondelete="RESTRICT"), index=True
    )
    merchant_counterparty_id: Mapped[int | None] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT")
    )
    purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    transaction_direction: Mapped[str] = mapped_column(String(20))
    normalization_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system_id",
            "payroll_run_source_id",
            "normalization_version",
            name="uq_payroll_run_source",
        ),
        UniqueConstraint("tenant_id", "canonical_hash", name="uq_payroll_run_hash"),
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
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT")
    )
    payroll_run_source_id: Mapped[str] = mapped_column(String(255))
    pay_period_start: Mapped[date | None] = mapped_column(Date())
    pay_period_end: Mapped[date | None] = mapped_column(Date())
    pay_date: Mapped[date] = mapped_column(Date(), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30))
    gross_pay_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employee_deductions_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    employer_contributions_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    reimbursement_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    net_pay_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    normalization_version: Mapped[str] = mapped_column(String(30))
    canonical_hash: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PayrollEntry(Base):
    __tablename__ = "payroll_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "canonical_hash", name="uq_payroll_entry_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    payroll_run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="RESTRICT"), index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), index=True
    )
    staging_payroll_summary_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_payroll_summaries.id", ondelete="RESTRICT"), unique=True
    )
    staging_payroll_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("staging_payroll_details.id", ondelete="RESTRICT"), unique=True
    )
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
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id", ondelete="RESTRICT"))
    normalization_version: Mapped[str] = mapped_column(String(30))
    canonical_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CanonicalRecordLineage(Base):
    __tablename__ = "canonical_record_lineage"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "canonical_entity_type",
            "canonical_entity_id",
            "staging_entity_type",
            "staging_entity_id",
            "transformation_version",
            name="uq_canonical_lineage",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    canonical_entity_type: Mapped[str] = mapped_column(String(50), index=True)
    canonical_entity_id: Mapped[int] = mapped_column(Integer(), index=True)
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT")
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT")
    )
    raw_source_row_id: Mapped[int] = mapped_column(
        ForeignKey("raw_source_rows.id", ondelete="RESTRICT")
    )
    staging_entity_type: Mapped[str] = mapped_column(String(50), index=True)
    staging_entity_id: Mapped[int] = mapped_column(Integer(), index=True)
    source_row_number: Mapped[int] = mapped_column(Integer())
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    transformation_name: Mapped[str] = mapped_column(String(100))
    transformation_version: Mapped[str] = mapped_column(String(30))
    mapping_code: Mapped[str] = mapped_column(String(100))
    mapping_version: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NormalizationMapping(Base):
    __tablename__ = "normalization_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_normalization_mapping_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(30))
    source_record_type: Mapped[str] = mapped_column(String(50), index=True)
    target_record_type: Mapped[str] = mapped_column(String(50))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NormalizationControlTotal(Base):
    __tablename__ = "normalization_control_totals"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "control_name", name="uq_normalization_control"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    control_name: Mapped[str] = mapped_column(String(100))
    staging_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    canonical_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    difference_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(30), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NormalizationException(Base):
    __tablename__ = "normalization_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "exception_fingerprint", name="uq_normalization_exception_fingerprint"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    staging_entity_type: Mapped[str] = mapped_column(String(50))
    staging_entity_id: Mapped[int] = mapped_column(Integer())
    exception_code: Mapped[str] = mapped_column(String(100), index=True)
    exception_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    field_name: Mapped[str | None] = mapped_column(String(100))
    observed_value: Mapped[str | None] = mapped_column(Text())
    expected_value: Mapped[str | None] = mapped_column(Text())
    message: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(30), index=True)
    exception_fingerprint: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
