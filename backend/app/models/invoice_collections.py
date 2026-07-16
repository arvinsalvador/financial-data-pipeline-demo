from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InvoiceCollectionsReconciliationRun(Base):
    __tablename__ = "invoice_collections_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "input_fingerprint",
            "ruleset_fingerprint",
            "reconciliation_version",
            name="uq_invoice_collections_input",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), unique=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date, index=True)
    aging_as_of_date: Mapped[date] = mapped_column(Date, index=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), index=True
    )
    generated_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="RESTRICT"), index=True
    )
    validation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="SET NULL"), index=True
    )
    included_customer_count: Mapped[int] = mapped_column(Integer, default=0)
    included_deal_count: Mapped[int] = mapped_column(Integer, default=0)
    included_invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    included_payment_count: Mapped[int] = mapped_column(Integer, default=0)
    included_bank_deposit_count: Mapped[int] = mapped_column(Integer, default=0)
    included_gl_record_count: Mapped[int] = mapped_column(Integer, default=0)
    automatically_matched_count: Mapped[int] = mapped_column(Integer, default=0)
    suggested_match_count: Mapped[int] = mapped_column(Integer, default=0)
    partially_matched_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_payment_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_deposit_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_gl_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_payment_count: Mapped[int] = mapped_column(Integer, default=0)
    exception_count: Mapped[int] = mapped_column(Integer, default=0)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    invoice_paid_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    invoice_balance_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    payment_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    applied_payment_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    unapplied_payment_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    bank_deposit_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    gl_receivable_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    gl_cash_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    matched_collection_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    reconciliation_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    ruleset_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsReconciliationRule(Base):
    __tablename__ = "invoice_collections_reconciliation_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_invoice_collections_rule"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(30))
    rule_type: Mapped[str] = mapped_column(String(50))
    execution_order: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_accept: Mapped[bool] = mapped_column(Boolean, default=False)
    minimum_confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsCandidate(Base):
    __tablename__ = "invoice_collections_candidates"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "candidate_fingerprint",
            name="uq_invoice_collections_candidate",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_rules.id", ondelete="RESTRICT")
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    crm_deal_id: Mapped[str | None] = mapped_column(String(255), index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    gl_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    candidate_type: Mapped[str] = mapped_column(String(60), index=True)
    match_group_key: Mapped[str | None] = mapped_column(String(255))
    amount_difference: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    date_difference_days: Mapped[int | None] = mapped_column(Integer)
    reference_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    customer_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    description_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    amount_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    date_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    total_confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), index=True)
    candidate_status: Mapped[str] = mapped_column(String(40), index=True)
    reason_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsMatchGroup(Base):
    __tablename__ = "invoice_collections_match_groups"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "group_fingerprint", name="uq_invoice_collections_group"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    group_type: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    payment_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    deposit_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    gl_total: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    difference_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    reconciliation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_rules.id", ondelete="RESTRICT")
    )
    auto_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))
    group_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsMatch(Base):
    __tablename__ = "invoice_collections_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_match_groups.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str | None] = mapped_column(String(255))
    crm_deal_id: Mapped[str | None] = mapped_column(String(255))
    invoice_id: Mapped[str | None] = mapped_column(String(255), index=True)
    invoice_line_id: Mapped[str | None] = mapped_column(String(255))
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_application_id: Mapped[str | None] = mapped_column(String(255))
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    gl_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_collections_candidates.id", ondelete="SET NULL")
    )
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    match_component: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    status: Mapped[str] = mapped_column(String(40))
    rule_code: Mapped[str] = mapped_column(String(120))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsAllocation(Base):
    __tablename__ = "invoice_collections_allocations"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "allocation_type",
            "invoice_id",
            "payment_id",
            "bank_transaction_id",
            "gl_record_id",
            name="uq_invoice_collections_allocation",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_match_groups.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    invoice_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_application_id: Mapped[str | None] = mapped_column(String(255))
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    gl_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    allocation_type: Mapped[str] = mapped_column(String(60))
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceCollectionsException(Base):
    __tablename__ = "invoice_collections_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "exception_fingerprint",
            name="uq_invoice_collections_exception",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    exception_code: Mapped[str] = mapped_column(String(120), index=True)
    exception_type: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str | None] = mapped_column(String(255))
    crm_deal_id: Mapped[str | None] = mapped_column(String(255))
    invoice_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    gl_record_id: Mapped[str | None] = mapped_column(String(255))
    match_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_collections_match_groups.id", ondelete="CASCADE")
    )
    message: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[str | None] = mapped_column(String(255))
    expected_value: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30))
    exception_fingerprint: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceCollectionsControlTotal(Base):
    __tablename__ = "invoice_collections_control_totals"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "control_name",
            "invoice_id",
            name="uq_invoice_collections_control",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str | None] = mapped_column(String(255))
    invoice_id: Mapped[str | None] = mapped_column(String(255), index=True)
    control_name: Mapped[str] = mapped_column(String(100), index=True)
    invoice_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    payment_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    deposit_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    gl_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    difference_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    tolerance: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceCollectionsDecision(Base):
    __tablename__ = "invoice_collections_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_match_groups.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(String(40))
    previous_status: Mapped[str] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceCollectionsReport(Base):
    __tablename__ = "invoice_collections_reports"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "report_type", name="uq_invoice_collections_report"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    report_type: Mapped[str] = mapped_column(String(100), index=True)
    relative_path: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountsReceivableAgingSnapshot(Base):
    __tablename__ = "accounts_receivable_aging_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "customer_id", name="uq_ar_aging_snapshot_customer"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_collections_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    customer_id: Mapped[str] = mapped_column(String(255), index=True)
    invoice_count: Mapped[int] = mapped_column(Integer)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    days_1_30_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    days_31_60_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    days_61_90_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    over_90_days_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    total_outstanding: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    disputed_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    unapplied_credit_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountsReceivableAgingBucket(Base):
    __tablename__ = "accounts_receivable_aging_buckets"
    __table_args__ = (
        UniqueConstraint("aging_snapshot_id", "invoice_id", name="uq_ar_aging_bucket_invoice"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    aging_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("accounts_receivable_aging_snapshots.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    invoice_id: Mapped[str] = mapped_column(String(255), index=True)
    customer_id: Mapped[str] = mapped_column(String(255), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    days_outstanding: Mapped[int] = mapped_column(Integer)
    aging_bucket: Mapped[str] = mapped_column(String(20), index=True)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    applied_payment_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
