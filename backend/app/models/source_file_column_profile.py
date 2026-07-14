from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
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
    from app.models.source_file_profile import SourceFileProfile


class SourceFileColumnProfile(Base):
    __tablename__ = "source_file_column_profiles"
    __table_args__ = (
        UniqueConstraint(
            "source_file_profile_id", "column_position", name="uq_column_profile_position"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_profile_id: Mapped[int] = mapped_column(
        ForeignKey("source_file_profiles.id", ondelete="CASCADE"), index=True
    )
    column_name: Mapped[str] = mapped_column(String(255))
    column_position: Mapped[int] = mapped_column(Integer())
    inferred_data_type: Mapped[str] = mapped_column(String(30), index=True)
    original_data_type: Mapped[str] = mapped_column(String(30), default="string")
    row_count: Mapped[int] = mapped_column(Integer())
    null_count: Mapped[int] = mapped_column(Integer())
    non_null_count: Mapped[int] = mapped_column(Integer())
    null_percentage: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    unique_count: Mapped[int] = mapped_column(Integer())
    duplicate_value_count: Mapped[int] = mapped_column(Integer())
    minimum_value: Mapped[str | None] = mapped_column(String(500))
    maximum_value: Mapped[str | None] = mapped_column(String(500))
    mean_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    median_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    standard_deviation: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    minimum_length: Mapped[int | None] = mapped_column(Integer())
    maximum_length: Mapped[int | None] = mapped_column(Integer())
    average_length: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    earliest_date: Mapped[date | None] = mapped_column(Date())
    latest_date: Mapped[date | None] = mapped_column(Date())
    sample_values_json: Mapped[list[str] | None] = mapped_column(JSON())
    detected_formats_json: Mapped[list[str] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_file_profile: Mapped["SourceFileProfile"] = relationship(back_populates="columns")
