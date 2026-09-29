from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional
from uuid import UUID
from datetime import datetime

OrderStatus = Literal["draft", "pending_payment", "paid", "fulfilled", "cancelled", "refunded"]
PaymentStatus = Literal["pending", "authorized", "approved", "partially_refunded", "rejected", "cancelled", "refunded"]
ShippingStatus = Literal["pending", "preparing", "shipped", "delivered", "returned"]


class OrderLineCreate(BaseModel):
    variant_id: UUID | str
    quantity: int = Field(..., gt=0)
    unit_price: float | None = Field(default=None, ge=0)


class OrderCreate(BaseModel):
    currency: str = Field(default="ARS", min_length=3, max_length=3)
    lines: List[OrderLineCreate] = Field(default_factory=list)
    shipping_amount: float | None = Field(default=None, ge=0)
    tax_amount: float | None = Field(default=None, ge=0)
    discount_amount: float | None = Field(default=None, ge=0)
    shipping_address: dict | None = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class OrderLineRead(BaseModel):
    id: UUID
    variant_id: UUID
    quantity: int
    unit_price: float
    line_total: float

    model_config = ConfigDict(from_attributes=True)


class PaymentRead(BaseModel):
    id: UUID
    provider: str
    provider_payment_id: Optional[str]
    status: PaymentStatus
    status_detail: Optional[str]
    amount: float
    refunded_amount: float
    currency: str
    init_point: Optional[str]
    sandbox_init_point: Optional[str]
    refunded_at: Optional[datetime]
    refund_reason: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class PaymentRefundCreate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    reason: Optional[str] = Field(default=None, max_length=240)
    restock_items: Optional[bool] = None


class PaymentRefundRead(BaseModel):
    id: UUID
    amount: float
    reason: Optional[str]
    provider_refund_id: Optional[str]
    status_detail: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentWebhookEventRead(BaseModel):
    id: UUID
    event_id: str
    request_id: Optional[str]
    event_type: Optional[str]
    outcome: Optional[str]
    processed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentAuditRead(BaseModel):
    payment: PaymentRead
    refunds: List[PaymentRefundRead] = Field(default_factory=list)
    webhook_events: List[PaymentWebhookEventRead] = Field(default_factory=list)


class ShipmentRead(BaseModel):
    id: UUID
    status: ShippingStatus
    carrier: Optional[str]
    tracking_number: Optional[str]
    shipped_at: Optional[datetime]
    delivered_at: Optional[datetime]
    address: Optional[dict]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ShipmentCreate(BaseModel):
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    address: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class OrderRead(BaseModel):
    id: UUID
    user_id: UUID | None
    applied_promotion_id: UUID | None
    status: OrderStatus
    payment_status: PaymentStatus
    shipping_status: ShippingStatus
    currency: str
    subtotal_amount: float
    discount_amount: float
    shipping_amount: float
    tax_amount: float
    total_amount: float
    shipping_address: Optional[dict]
    notes: Optional[str]
    paid_at: Optional[datetime]
    fulfilled_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    refunded_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime] = None
    lines: List[OrderLineRead] = Field(default_factory=list)
    payments: List[PaymentRead] = Field(default_factory=list)
    shipments: List[ShipmentRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
