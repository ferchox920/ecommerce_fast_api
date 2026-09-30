from __future__ import annotations

from datetime import datetime, date
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class EventMetadata(BaseModel):
    context: str | None = Field(default=None, max_length=50)
    referrer: str | None = None
    device: str | None = None
    quantity: int | None = None
    order_id: UUID | None = None


class EventCreate(BaseModel):
    event_type: str = Field(pattern=r"^(view|click|add_to_cart|purchase)$")
    product_id: UUID
    user_id: UUID | None = None
    session_id: UUID | None = None
    timestamp: datetime | None = None
    price: float | None = Field(default=None, ge=0)
    metadata: EventMetadata | None = None


class ProductEngagementRead(BaseModel):
    product_id: UUID
    date: date
    views: int
    clicks: int
    carts: int
    purchases: int
    revenue: float

    model_config = ConfigDict(from_attributes=True)


class CustomerEngagementRead(BaseModel):
    customer_id: str
    date: date
    views: int
    clicks: int
    carts: int
    purchases: int
    points_earned: int

    model_config = ConfigDict(from_attributes=True)
