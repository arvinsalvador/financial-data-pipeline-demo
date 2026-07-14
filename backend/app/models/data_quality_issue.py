from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.pipeline_run import PipelineRun
    from app.models.source_file import SourceFile
    from app.models.source_file_profile import SourceFileProfile


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    source_file_profile_id: Mapped[int] = mapped_column(
        ForeignKey("source_file_profiles.id", ondelete="CASCADE"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    column_name: Mapped[str | None] = mapped_column(String(255), index=True)
    row_number: Mapped[int | None] = mapped_column(Integer())
    issue_code: Mapped[str] = mapped_column(String(100), index=True)
    issue_type: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text())
    observed_value: Mapped[str | None] = mapped_column(Text())
    expected_value: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(20), index=True, default="open")
    issue_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_file: Mapped["SourceFile"] = relationship(back_populates="data_quality_issues")
    source_file_profile: Mapped["SourceFileProfile"] = relationship(back_populates="issues")
    pipeline_run: Mapped["PipelineRun"] = relationship(back_populates="data_quality_issues")
