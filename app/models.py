from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.config import settings
from app.enums import StaffRole, ThreatEnum

threat_type = SQLEnum(ThreatEnum, name="threat", values_callable=lambda enum: [item.value for item in enum])
staff_role_type = SQLEnum(StaffRole, name="staff_role", values_callable=lambda enum: [item.value for item in enum])


class Cities(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(25), unique=True)
    name: Mapped[str] = mapped_column(String(25))
    threat: Mapped[ThreatEnum] = mapped_column(threat_type, default=ThreatEnum.CALM, server_default="calm")
    monitoring_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    event_id: Mapped[str | None] = mapped_column(String(80))
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    listener_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_id: Mapped[int] = mapped_column(BigInteger, server_default="0")
    context: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    @property
    def confirmed(self):
        now = datetime.now(timezone.utc)
        return bool(
            self.monitoring_enabled and self.event_id
            and self.listener_seen_at and self.listener_seen_at > now - timedelta(seconds=30)
            and (
                self.threat == ThreatEnum.CALM
                or (self.event_at and self.event_at + timedelta(seconds=settings.alert_ttl_seconds) > now)
            )
        )


class Clients(Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_city_active", "city_id", "is_active"),
        Index("ix_clients_deactivated", "deactivated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fcm_token: Mapped[str] = mapped_column(Text, unique=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassificationHistory(Base):
    __tablename__ = "classification_history"
    __table_args__ = (
        UniqueConstraint("city_id", "source_chat_id", "source_message_id", name="uq_history_source_city"),
        Index("ix_history_city_occurred", "city_id", "occurred_at"),
        Index("ix_history_occurred", "occurred_at"),
        Index("ix_history_processing", "city_id", "status", "source_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    telegram_message: Mapped[str] = mapped_column(Text)
    first_answer: Mapped[str | None] = mapped_column(Text)
    final_answer: Mapped[str | None] = mapped_column(Text)
    threat: Mapped[ThreatEnum | None] = mapped_column(threat_type, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(12), server_default="done")
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(80))


class StaffUsers(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[StaffRole] = mapped_column(staff_role_type, default=StaffRole.ADMIN)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffSessions(Base):
    __tablename__ = "staff_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
