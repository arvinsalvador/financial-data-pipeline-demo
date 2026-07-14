from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemCheck(Base):
    __tablename__ = "system_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    component: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
