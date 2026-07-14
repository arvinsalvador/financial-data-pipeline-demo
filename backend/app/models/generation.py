from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
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


class GeneratedDatasetRun(Base):
    __tablename__ = "generated_dataset_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "input_fingerprint",
            "generator_version",
            "random_seed",
            name="uq_generated_dataset_inputs",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), unique=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    generator_version: Mapped[str] = mapped_column(String(30))
    random_seed: Mapped[int] = mapped_column(Integer())
    generation_date: Mapped[date] = mapped_column(Date())
    base_date_start: Mapped[date | None] = mapped_column(Date())
    base_date_end: Mapped[date | None] = mapped_column(Date())
    source_bank_transaction_count: Mapped[int] = mapped_column(Integer(), default=0)
    source_credit_card_transaction_count: Mapped[int] = mapped_column(Integer(), default=0)
    source_payroll_run_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_customer_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_vendor_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_deal_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_invoice_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_payment_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_ap_bill_count: Mapped[int] = mapped_column(Integer(), default=0)
    generated_gl_entry_count: Mapped[int] = mapped_column(Integer(), default=0)
    status: Mapped[str] = mapped_column(String(30), index=True)
    file_count: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    record_count: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GeneratedSourceFile(Base):
    __tablename__ = "generated_source_files"
    __table_args__ = (
        UniqueConstraint("generated_dataset_run_id", "file_type", name="uq_generated_file_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    generated_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), index=True
    )
    file_type: Mapped[str] = mapped_column(String(100), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256_checksum: Mapped[str] = mapped_column(String(64), index=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    record_count: Mapped[int] = mapped_column(Integer())
    column_count: Mapped[int] = mapped_column(Integer())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedRecordLink(Base):
    __tablename__ = "generated_record_links"
    __table_args__ = (
        UniqueConstraint(
            "generated_dataset_run_id",
            "generated_record_key",
            "relationship_type",
            "related_entity_type",
            "related_entity_id",
            name="uq_generated_record_link",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    generated_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    generated_file_type: Mapped[str] = mapped_column(String(100), index=True)
    generated_record_key: Mapped[str] = mapped_column(String(255), index=True)
    relationship_type: Mapped[str] = mapped_column(String(100), index=True)
    related_entity_type: Mapped[str] = mapped_column(String(100), index=True)
    related_entity_id: Mapped[str] = mapped_column(String(255), index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationControlTotal(Base):
    __tablename__ = "generation_control_totals"
    __table_args__ = (
        UniqueConstraint("generated_dataset_run_id", "control_name", name="uq_generation_control"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    generated_dataset_run_id: Mapped[int] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="CASCADE"), index=True
    )
    control_name: Mapped[str] = mapped_column(String(120), index=True)
    expected_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    actual_value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    difference: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    status: Mapped[str] = mapped_column(String(30), index=True)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationException(Base):
    __tablename__ = "generation_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "input_fingerprint", "exception_code", name="uq_generation_exception"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    generated_dataset_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_dataset_runs.id", ondelete="SET NULL"), index=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    exception_code: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    message: Mapped[str] = mapped_column(Text())
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
