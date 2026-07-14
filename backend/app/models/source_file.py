from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.data_quality_issue import DataQualityIssue
    from app.models.pipeline_run import PipelineRun
    from app.models.source_file_profile import SourceFileProfile
    from app.models.source_system import SourceSystem


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sha256_checksum", name="uq_source_file_tenant_checksum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    source_system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="RESTRICT"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(330), unique=True)
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    file_extension: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str] = mapped_column(String(255))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger())
    sha256_checksum: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_system: Mapped["SourceSystem"] = relationship(back_populates="source_files")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="source_file")
    profiles: Mapped[list["SourceFileProfile"]] = relationship(back_populates="source_file")
    data_quality_issues: Mapped[list["DataQualityIssue"]] = relationship(
        back_populates="source_file"
    )
