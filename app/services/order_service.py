from __future__ import annotations

import uuid
import hashlib
import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartStatus
from app.models.order import (
    Order,
    OrderLine,
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
    Shipment,
)
from app.models.product import Product, ProductVariant
from app.models.promotion import PromotionStatus
from app.models.user import User
from app.schemas.order import OrderCreate, OrderLineCreate, ShipmentCreate
from app.services import inventory_service, notification_service, promotion_service
from app.services.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
    ServiceError,
)
from app.services.pricing import get_variant_effective_price


def _as_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise DomainValidationError(f"Invalid UUID for {field}") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _recompute_totals(order: Order) -> None:
    subtotal = sum(float(line.line_total) for line in order.lines)
    order.subtotal_amount = subtotal
    order.total_amount = (
        subtotal
        - float(order.discount_amount or 0)
        + float(order.shipping_amount or 0)
        + float(order.tax_amount or 0)
    )


async def _reserve_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None) -> None:
    try:
        await inventory_service.reserve_stock(db, variant, quantity, reason)
    except ServiceError as exc:
        raise ConflictError(exc.detail) from exc


async def _release_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None) -> None:
    try:
        await inventory_service.release_stock(db, variant, quantity, reason)
    except ServiceError as exc:
        raise ConflictError(exc.detail) from exc


async def _commit_sale(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None) -> None:
    try:
        await inventory_service.commit_sale(db, variant, quantity, reason)
    except ServiceError as exc:
        raise ConflictError(exc.detail) from exc


async def _load_order_eager(db: AsyncSession, order: Order) -> None:
    await db.refresh(order)
    await db.refresh(order, attribute_names=["lines"])
    await db.refresh(order, attribute_names=["payments"])
    await db.refresh(order, attribute_names=["shipments"])


async def list_orders(
    db: AsyncSession,
    *,
    status_filter: OrderStatus | None = None,
    payment_status: PaymentStatus | None = None,
    shipping_status: ShippingStatus | None = None,
    user_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Order]:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.lines),
            selectinload(Order.payments),
            selectinload(Order.shipments),
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if shipping_status:
        stmt = stmt.where(Order.shipping_status == shipping_status)
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)

    result = await db.execute(stmt)
    orders = result.scalars().all()
    return orders


async def get_order(db: AsyncSession, order_id: str) -> Order:
    order = await db.get(
        Order,
        _as_uuid(order_id, "order_id"),
        options=[
            selectinload(Order.lines),
            selectinload(Order.payments),
            selectinload(Order.shipments),
        ],
    )
    if not order:
        raise ResourceNotFoundError("Order not found")
    await db.refresh(order, attribute_names=["lines", "payments", "shipments"])
    return order


async def _add_line(
    db: AsyncSession,
    order: Order,
    payload: OrderLineCreate,
    *,
    reserve_stock: bool,
) -> OrderLine:
    variant = await db.get(ProductVariant, _as_uuid(payload.variant_id, "variant_id"))
    if not variant:
        raise ResourceNotFoundError("Variant not found")
    product = await db.get(Product, variant.product_id)
    if not variant.active or product is None or not product.active:
        raise ConflictError("Variant is not available")
    if product.currency != order.currency:
        raise DomainValidationError("Variant currency does not match order currency")

    if reserve_stock:
        await _reserve_stock(db, variant, payload.quantity, reason=f"order:{order.id}")

    unit_price = await get_variant_effective_price(db, variant)

    line = OrderLine(
        order=order,
        variant_id=variant.id,
        quantity=payload.quantity,
        unit_price=unit_price,
        line_total=unit_price * payload.quantity,
    )
    db.add(line)
    await db.flush()
    return line


async def create_order(
    db: AsyncSession,
    current_user_id: str | None,
    payload: OrderCreate,
    *,
    idempotency_key: str | None = None,
) -> tuple[Order, bool]:
    if payload.currency != "ARS":
        raise DomainValidationError("Unsupported order currency")
    if any((payload.shipping_amount, payload.tax_amount, payload.discount_amount)):
        raise DomainValidationError("Order monetary adjustments must be calculated by the server")
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    if idempotency_key:
        if current_user_id is None:
            raise DomainValidationError("Authenticated user required for idempotent orders")
        await db.get(User, current_user_id, with_for_update=True)
        previous = await db.scalar(
            select(Order).where(
                Order.user_id == current_user_id,
                Order.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            if previous.request_fingerprint != fingerprint:
                raise ConflictError("Idempotency key was used for a different order")
            await _load_order_eager(db, previous)
            return previous, False
    order = Order(
        user_id=str(current_user_id) if current_user_id is not None else None,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint if idempotency_key else None,
        currency=payload.currency or "ARS",
        status=OrderStatus.draft,
        payment_status=PaymentStatus.pending,
        shipping_status=ShippingStatus.pending,
        shipping_amount=float(payload.shipping_amount or 0),
        tax_amount=float(payload.tax_amount or 0),
        discount_amount=float(payload.discount_amount or 0),
        shipping_address=payload.shipping_address,
        notes=payload.notes,
    )
    db.add(order)
    await db.flush()

    for line in payload.lines:
        await _add_line(db, order, line, reserve_stock=True)

    await db.refresh(order, attribute_names=["lines"])
    if order.lines:
        order.status = OrderStatus.pending_payment

    _recompute_totals(order)
    db.add(order)
    await db.flush()

    await notification_service.notify_new_order(db, order)
    await notification_service.notify_order_status(
        db,
        order,
        title="Orden creada",
        message="Tu orden ha sido creada y está pendiente de pago.",
    )
    await _load_order_eager(db, order)
    return order, True


async def add_line(db: AsyncSession, order: Order, payload: OrderLineCreate) -> Order:
    order = await db.get(Order, order.id, with_for_update=True, populate_existing=True)
    if order.status not in (OrderStatus.draft, OrderStatus.pending_payment):
        raise ConflictError("Order lines cannot be changed in this state")
    await _add_line(db, order, payload, reserve_stock=True)
    await db.refresh(order, attribute_names=["lines"])
    _recompute_totals(order)
    db.add(order)
    await db.flush()
    await _load_order_eager(db, order)
    return order


async def create_order_from_cart(
    db: AsyncSession, cart: Cart, *, promotion_id: uuid.UUID | None = None
) -> Order:
    cart = await db.get(Cart, cart.id, with_for_update=True, populate_existing=True)
    if cart.status == CartStatus.converted:
        existing = await db.scalar(select(Order).where(Order.source_cart_id == cart.id))
        if existing is not None:
            if existing.applied_promotion_id != promotion_id:
                raise ConflictError("Checkout parameters changed on retry")
            await _load_order_eager(db, existing)
            return existing
        raise ConflictError("Cart was already converted")
    if cart.status != CartStatus.active:
        raise ConflictError("Cart is not active")
    await db.refresh(cart, attribute_names=["items"])
    if not cart.items:
        raise DomainValidationError("Cart has no items")

    order = Order(
        user_id=str(cart.user_id) if cart.user_id is not None else None,
        source_cart_id=cart.id,
        applied_promotion_id=promotion_id,
        currency=cart.currency,
        status=OrderStatus.draft,
        payment_status=PaymentStatus.pending,
        shipping_status=ShippingStatus.pending,
        subtotal_amount=0,
        discount_amount=0,
        shipping_amount=float(getattr(cart, "shipping_amount", 0) or 0),
        total_amount=0,
    )
    db.add(order)
    await db.flush()

    for item in cart.items:
        line_payload = OrderLineCreate(
            variant_id=item.variant_id,
            quantity=item.quantity,
            unit_price=float(item.unit_price),
        )
        await _add_line(db, order, line_payload, reserve_stock=True)

    await db.refresh(order, attribute_names=["lines"])
    if promotion_id:
        promotion = await promotion_service.get_promotion(db, promotion_id)
        if promotion.status != PromotionStatus.active or promotion.scope not in ("product", "category"):
            raise ConflictError("Promotion cannot be applied to this cart")
        percent = Decimal(str((promotion.benefits_json or {}).get("discount_percent", 0)))
        if percent <= 0 or percent > 100:
            raise ConflictError("Promotion discount is invalid")
        eligible_subtotal = Decimal("0")
        for line in order.lines:
            variant = await db.get(ProductVariant, line.variant_id)
            product = await db.get(Product, variant.product_id)
            eligible, _ = promotion_service.evaluate_eligibility(
                promotion,
                user_id=str(cart.user_id) if cart.user_id else None,
                product_id=product.id,
                category_id=product.category_id,
                order_total=float(sum(Decimal(str(item.line_total)) for item in order.lines)),
            )
            if eligible:
                eligible_subtotal += Decimal(str(line.line_total))
        if eligible_subtotal <= 0:
            raise ConflictError("Promotion does not apply to cart items")
        order.discount_amount = float((eligible_subtotal * percent / 100).quantize(Decimal("0.01")))
    order.status = OrderStatus.pending_payment if order.lines else OrderStatus.draft
    _recompute_totals(order)

    cart.status = CartStatus.converted
    db.add(cart)
    db.add(order)
    await db.flush()

    # ⬇️ Igualamos el comportamiento al de create_order:
    await notification_service.notify_new_order(db, order)
    await notification_service.notify_order_status(
        db,
        order,
        title="Orden creada",
        message="Tu orden ha sido creada y está pendiente de pago.",
    )

    await _load_order_eager(db, order)
    return order


async def set_status_paid(db: AsyncSession, order: Order) -> Order:
    order = await db.get(Order, order.id, with_for_update=True, populate_existing=True)
    if order.status not in [OrderStatus.pending_payment, OrderStatus.draft]:
        raise ConflictError("Order cannot be marked as paid")
    if order.total_amount <= 0:
        raise DomainValidationError("Order total must be greater than 0")

    await db.refresh(order, attribute_names=["lines"])

    for line in order.lines:
        variant = await db.get(ProductVariant, line.variant_id)
        if not variant:
            raise ResourceNotFoundError("Variant not found")
        await _commit_sale(db, variant, line.quantity, reason=f"order:{order.id}")

    order.status = OrderStatus.paid
    order.payment_status = PaymentStatus.approved
    order.paid_at = _utcnow()
    db.add(order)
    await db.flush()

    await notification_service.notify_order_status(
        db,
        order,
        title="Orden pagada",
        message="Tu orden ha sido pagada correctamente.",
    )
    await _load_order_eager(db, order)
    return order


async def cancel_order(db: AsyncSession, order: Order) -> Order:
    order = await db.get(Order, order.id, with_for_update=True, populate_existing=True)
    if order.status in [OrderStatus.fulfilled, OrderStatus.refunded, OrderStatus.cancelled]:
        raise ConflictError("Order cannot be cancelled")
    if order.status == OrderStatus.paid:
        raise ConflictError("Paid orders require a refund process")

    await db.refresh(order, attribute_names=["lines"])

    for line in order.lines:
        variant = await db.get(ProductVariant, line.variant_id)
        if not variant:
            continue
        await _release_stock(db, variant, line.quantity, reason=f"order:{order.id}")

    order.status = OrderStatus.cancelled
    order.payment_status = PaymentStatus.cancelled
    order.cancelled_at = _utcnow()
    db.add(order)
    await db.flush()

    await notification_service.notify_order_status(
        db,
        order,
        title="Orden cancelada",
        message="Tu orden ha sido cancelada.",
    )
    await _load_order_eager(db, order)
    return order


async def fulfill_order(db: AsyncSession, order: Order, payload: ShipmentCreate | None = None) -> Order:
    order = await db.get(Order, order.id, with_for_update=True, populate_existing=True)
    if order.status != OrderStatus.paid:
        raise ConflictError("Only paid orders can be fulfilled")

    shipment_status = ShippingStatus.shipped
    shipped_at = _utcnow()
    delivered_at = None

    if payload:
        if payload.delivered_at:
            shipment_status = ShippingStatus.delivered
            delivered_at = payload.delivered_at
        if payload.shipped_at:
            shipped_at = payload.shipped_at

    shipment = Shipment(
        order=order,
        status=shipment_status,
        carrier=payload.carrier if payload else None,
        tracking_number=payload.tracking_number if payload else None,
        shipped_at=shipped_at,
        delivered_at=delivered_at,
        address=payload.address if payload else None,
        notes=payload.notes if payload else None,
    )
    db.add(shipment)

    order.status = OrderStatus.fulfilled
    order.shipping_status = shipment_status
    order.fulfilled_at = delivered_at or shipped_at
    db.add(order)
    await db.flush()

    await notification_service.notify_order_status(
        db,
        order,
        title="Orden enviada",
        message="Tu orden fue despachada, revisa el seguimiento disponible.",
    )
    await _load_order_eager(db, order)
    return order
