from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
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


class BankLedgerReconciliationRun(Base):
    __tablename__ = "bank_ledger_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "input_fingerprint",
            "ruleset_fingerprint",
            "reconciliation_version",
            name="uq_bank_ledger_reconciliation_input",
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
    date_from: Mapped[date] = mapped_column(Date(), index=True)
    date_to: Mapped[date] = mapped_column(Date(), index=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), index=True
    )
    generated_source_file_id: Mapped[int] = mapped_column(
        ForeignKey("generated_source_files.id", ondelete="RESTRICT")
    )
    validation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="SET NULL"), index=True
    )
    included_bank_transaction_count: Mapped[int] = mapped_column(Integer(), default=0)
    included_ledger_line_count: Mapped[int] = mapped_column(Integer(), default=0)
    automatically_matched_count: Mapped[int] = mapped_column(Integer(), default=0)
    suggested_match_count: Mapped[int] = mapped_column(Integer(), default=0)
    partially_matched_count: Mapped[int] = mapped_column(Integer(), default=0)
    unmatched_bank_count: Mapped[int] = mapped_column(Integer(), default=0)
    unmatched_ledger_count: Mapped[int] = mapped_column(Integer(), default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer(), default=0)
    reversal_count: Mapped[int] = mapped_column(Integer(), default=0)
    exception_count: Mapped[int] = mapped_column(Integer(), default=0)
    total_bank_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    total_ledger_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    total_matched_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    total_unmatched_bank_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    total_unmatched_ledger_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), default=0)
    reconciliation_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    ruleset_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationRule(Base):
    __tablename__ = "reconciliation_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_reconciliation_rule_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text())
    version: Mapped[str] = mapped_column(String(30))
    rule_type: Mapped[str] = mapped_column(String(50), index=True)
    execution_order: Mapped[int] = mapped_column(Integer())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, index=True)
    auto_accept: Mapped[bool] = mapped_column(Boolean(), default=False)
    minimum_confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationCandidate(Base):
    __tablename__ = "reconciliation_candidates"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "candidate_fingerprint", name="uq_reconciliation_candidate"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_rules.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    ledger_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    match_group_key: Mapped[str | None] = mapped_column(String(255), index=True)
    candidate_type: Mapped[str] = mapped_column(String(40), index=True)
    amount_difference: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    date_difference_days: Mapped[int | None] = mapped_column(Integer())
    reference_score: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    description_score: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    amount_score: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    date_score: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    total_confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), index=True)
    candidate_status: Mapped[str] = mapped_column(String(40), index=True)
    reason_json: Mapped[dict[str, Any]] = mapped_column(JSON())
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationMatchGroup(Base):
    __tablename__ = "reconciliation_match_groups"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "group_fingerprint", name="uq_reconciliation_group"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_rule_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_rules.id", ondelete="RESTRICT")
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    group_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), index=True)
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    bank_total: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    ledger_total: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    difference_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    auto_accepted: Mapped[bool] = mapped_column(Boolean(), default=False, index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))
    group_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"
    __table_args__ = (
        UniqueConstraint(
            "match_group_id",
            "bank_transaction_id",
            "ledger_record_id",
            name="uq_reconciliation_match_member",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_match_groups.id", ondelete="CASCADE"), index=True
    )
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    ledger_record_id: Mapped[str] = mapped_column(String(255), index=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("reconciliation_candidates.id", ondelete="SET NULL")
    )
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    status: Mapped[str] = mapped_column(String(40), index=True)
    rule_code: Mapped[str] = mapped_column(String(120), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationAllocation(Base):
    __tablename__ = "reconciliation_allocations"
    __table_args__ = (
        UniqueConstraint(
            "match_group_id",
            "bank_transaction_id",
            "ledger_record_id",
            name="uq_reconciliation_allocation",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_match_groups.id", ondelete="CASCADE"), index=True
    )
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    ledger_record_id: Mapped[str] = mapped_column(String(255), index=True)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    allocation_direction: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationException(Base):
    __tablename__ = "reconciliation_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id", "exception_fingerprint", name="uq_reconciliation_exception"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    exception_code: Mapped[str] = mapped_column(String(120), index=True)
    exception_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"), index=True
    )
    ledger_record_id: Mapped[str | None] = mapped_column(String(255), index=True)
    match_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("reconciliation_match_groups.id", ondelete="SET NULL")
    )
    message: Mapped[str] = mapped_column(Text())
    observed_value: Mapped[str | None] = mapped_column(Text())
    expected_value: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    exception_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationControlTotal(Base):
    __tablename__ = "reconciliation_control_totals"
    __table_args__ = (
        UniqueConstraint("reconciliation_run_id", "control_name", name="uq_reconciliation_control"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    control_name: Mapped[str] = mapped_column(String(120), index=True)
    source_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    matched_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    unmatched_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    difference_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    tolerance: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(40), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReconciliationDecision(Base):
    __tablename__ = "reconciliation_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    match_group_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_match_groups.id", ondelete="RESTRICT"), index=True
    )
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[str] = mapped_column(String(30), index=True)
    previous_status: Mapped[str] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"
    __table_args__ = (
        UniqueConstraint("reconciliation_run_id", "report_type", name="uq_reconciliation_report"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    reconciliation_run_id: Mapped[int] = mapped_column(
        ForeignKey("bank_ledger_reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    reconciliation_version: Mapped[str] = mapped_column(String(30))
    report_type: Mapped[str] = mapped_column(String(80), index=True)
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
