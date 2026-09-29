import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class MovementKind(str, Enum):
    RECEIVE = "receive"
    ADJUST = "adjust"
    RESERVE = "reserve"
    RELEASE = "release"
    SALE = "sale"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        Index("ix_inventory_movements_variant_created", "variant_id", "created_at"),
        UniqueConstraint("variant_id", "idempotency_key", name="uq_inventory_movement_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[MovementKind] = mapped_column(SqlEnum(MovementKind, name="inventory_movement_type"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    if TYPE_CHECKING:  # pragma: no cover - for typing only
        from app.models.product import ProductVariant
        variant: Mapped["ProductVariant"]
    else:
        variant = relationship("ProductVariant", back_populates="movements")

