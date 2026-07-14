from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.source_file import SourceFile


class SourceSystem(Base):
    __tablename__ = "source_systems"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_source_system_tenant_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text())
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_files: Mapped[list["SourceFile"]] = relationship(back_populates="source_system")
