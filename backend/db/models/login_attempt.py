import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.models.base import Base


class LoginAttempt(Base):
    """Security audit record for an unsuccessful authentication attempt."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_username_attempted_at", "username", "attempted_at"),
        Index("ix_login_attempts_client_ip_attempted_at", "client_ip", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(150))
    client_ip: Mapped[str] = mapped_column(String(45))
    reason: Mapped[str] = mapped_column(String(32))
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
