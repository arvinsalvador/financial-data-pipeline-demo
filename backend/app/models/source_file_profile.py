from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_quality_issue import DataQualityIssue
    from app.models.pipeline_run import PipelineRun
    from app.models.source_file import SourceFile
    from app.models.source_file_column_profile import SourceFileColumnProfile


class SourceFileProfile(Base):
    __tablename__ = "source_file_profiles"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id", "profile_version", name="uq_source_file_profile_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    profile_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(50), index=True)
    encoding: Mapped[str | None] = mapped_column(String(50))
    delimiter: Mapped[str | None] = mapped_column(String(10))
    row_count: Mapped[int] = mapped_column(Integer(), default=0)
    column_count: Mapped[int] = mapped_column(Integer(), default=0)
    empty_row_count: Mapped[int] = mapped_column(Integer(), default=0)
    duplicate_row_count: Mapped[int] = mapped_column(Integer(), default=0)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    date_range_start: Mapped[date | None] = mapped_column(Date())
    date_range_end: Mapped[date | None] = mapped_column(Date())
    total_null_count: Mapped[int] = mapped_column(Integer(), default=0)
    total_non_null_count: Mapped[int] = mapped_column(Integer(), default=0)
    total_numeric_columns: Mapped[int] = mapped_column(Integer(), default=0)
    total_date_columns: Mapped[int] = mapped_column(Integer(), default=0)
    total_text_columns: Mapped[int] = mapped_column(Integer(), default=0)
    total_boolean_columns: Mapped[int] = mapped_column(Integer(), default=0)
    monetary_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    debit_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    credit_total: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    calculated_closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    running_balance_valid: Mapped[bool | None] = mapped_column(Boolean())
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    profile_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())

    source_file: Mapped["SourceFile"] = relationship(back_populates="profiles")
    pipeline_run: Mapped["PipelineRun"] = relationship(back_populates="profiles")
    columns: Mapped[list["SourceFileColumnProfile"]] = relationship(
        back_populates="source_file_profile",
        cascade="all, delete-orphan",
        order_by="SourceFileColumnProfile.column_position",
    )
    issues: Mapped[list["DataQualityIssue"]] = relationship(
        back_populates="source_file_profile", cascade="all, delete-orphan"
    )
