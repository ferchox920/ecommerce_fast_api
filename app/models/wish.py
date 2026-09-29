from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WishStatus(str, Enum):
    active = "active"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class Wish(Base):
    __tablename__ = "wishes"
    __table_args__ = (
        Index("ix_wishes_user_id", "user_id"),
        Index("ix_wishes_user_product", "user_id", "product_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    desired_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    notify_discount: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[WishStatus] = mapped_column(SqlEnum(WishStatus, name="wish_status"), default=WishStatus.active, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    notifications: Mapped[list["WishNotification"]] = relationship(
        "WishNotification", back_populates="wish", cascade="all, delete-orphan"
    )


class WishNotification(Base):
    __tablename__ = "wish_notifications"
    __table_args__ = (Index("ix_wish_notifications_wish_id", "wish_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wishes.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    wish: Mapped[Wish] = relationship("Wish", back_populates="notifications")
