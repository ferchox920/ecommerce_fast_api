import uuid
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import String, Text, DateTime, Enum as SqlEnum, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromotionType(str, Enum):
    category = "category"
    product = "product"
    customer = "customer"
    loyalty = "loyalty"


class PromotionStatus(str, Enum):
    draft = "draft"
    active = "active"
    scheduled = "scheduled"
    expired = "expired"


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (
        Index("ix_promotions_status", "status"),
        Index("ix_promotions_start_end", "start_at", "end_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[PromotionType] = mapped_column(SqlEnum(PromotionType), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False, default="global")
    criteria_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    benefits_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[PromotionStatus] = mapped_column(SqlEnum(PromotionStatus), default=PromotionStatus.draft, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    products: Mapped[list["PromotionProduct"]] = relationship("PromotionProduct", cascade="all, delete-orphan", back_populates="promotion")
    customers: Mapped[list["PromotionCustomer"]] = relationship("PromotionCustomer", cascade="all, delete-orphan", back_populates="promotion")

    # INTEGRATION: 'criteria_json' y 'benefits_json' se coordinarán con el motor de pricing/checkout.


class PromotionProduct(Base):
    __tablename__ = "promotion_products"

    promotion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)

    promotion: Mapped[Promotion] = relationship("Promotion", back_populates="products")


class PromotionCustomer(Base):
    __tablename__ = "promotion_customers"

    promotion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    promotion: Mapped[Promotion] = relationship("Promotion", back_populates="customers")
