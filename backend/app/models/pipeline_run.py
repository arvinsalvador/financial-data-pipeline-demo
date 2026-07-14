from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_quality_issue import DataQualityIssue
    from app.models.pipeline_run_step import PipelineRunStep
    from app.models.source_file import SourceFile
    from app.models.source_file_profile import SourceFileProfile


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pipeline_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_definitions.id", ondelete="RESTRICT"), index=True
    )
    run_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"), index=True
    )
    records_extracted: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    records_accepted: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    records_rejected: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_file: Mapped["SourceFile | None"] = relationship(back_populates="pipeline_runs")
    steps: Mapped[list["PipelineRunStep"]] = relationship(
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
        order_by="PipelineRunStep.step_order",
    )
    profiles: Mapped[list["SourceFileProfile"]] = relationship(back_populates="pipeline_run")
    data_quality_issues: Mapped[list["DataQualityIssue"]] = relationship(
        back_populates="pipeline_run"
    )
