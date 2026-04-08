from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentProvider,
    PaymentRefund,
    PaymentStatus,
    PaymentWebhookEvent,
)
from app.models.product import ProductVariant
from app.services import inventory_service, notification_service, order_service
from app.services.exceptions import ConflictError, DomainValidationError, ResourceNotFoundError
from app.services.payment_providers import (
    PaymentProviderConfigurationError,
    PaymentProviderError,
    mercado_pago,
)


MERCADO_PAGO_STATUS_MAP = {
    "pending": PaymentStatus.pending,
    "in_process": PaymentStatus.pending,
    "authorized": PaymentStatus.authorized,
    "approved": PaymentStatus.approved,
    "partially_refunded": PaymentStatus.partially_refunded,
    "rejected": PaymentStatus.rejected,
    "cancelled": PaymentStatus.cancelled,
    "refunded": PaymentStatus.refunded,
    "charged_back": PaymentStatus.refunded,
}


def _map_mp_status(value: str | None) -> PaymentStatus:
    if not value:
        return PaymentStatus.pending
    return MERCADO_PAGO_STATUS_MAP.get(value, PaymentStatus.pending)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: float | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _normalize_event_id(payload: dict, request_id: str | None) -> str:
    if request_id:
        return request_id
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_payment(db: AsyncSession, payment_id: str) -> Payment:
    try:
        payment_uuid = uuid.UUID(str(payment_id))
    except ValueError as exc:
        raise DomainValidationError("Invalid payment id") from exc
    payment = await db.get(Payment, payment_uuid)
    if not payment:
        raise ResourceNotFoundError("Payment not found")
    return payment


async def get_payment_audit(db: AsyncSession, payment: Payment) -> dict:
    refund_result = await db.execute(
        select(PaymentRefund)
        .where(PaymentRefund.payment_id == payment.id)
        .order_by(PaymentRefund.created_at.desc())
    )
    webhook_result = await db.execute(
        select(PaymentWebhookEvent)
        .where(PaymentWebhookEvent.payment_id == payment.id)
        .order_by(PaymentWebhookEvent.processed_at.desc())
    )
    await db.refresh(payment)
    return {
        "payment": payment,
        "refunds": refund_result.scalars().all(),
        "webhook_events": webhook_result.scalars().all(),
    }


async def _find_reusable_payment(
    db: AsyncSession,
    order_id,
    *,
    idempotency_key: str | None,
) -> Payment | None:
    if idempotency_key:
        result = await db.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .where(Payment.idempotency_key == idempotency_key)
            .limit(1)
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == order_id)
        .where(Payment.status.in_([PaymentStatus.pending, PaymentStatus.authorized, PaymentStatus.approved]))
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_payment_preference(
    db: AsyncSession,
    order: Order,
    *,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    if order.status not in [OrderStatus.pending_payment, OrderStatus.draft]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order is not ready to pay")
    if not order.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order has no items")

    reusable = await _find_reusable_payment(db, order.id, idempotency_key=idempotency_key)
    if reusable:
        await db.refresh(reusable)
        return reusable, False

    try:
        preference = mercado_pago.create_checkout_preference(order, idempotency_key=idempotency_key)
    except PaymentProviderConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except PaymentProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    preference_id = preference.get("id") or preference.get("preference_id")

    payment = Payment(
        order=order,
        provider=PaymentProvider.mercado_pago,
        provider_payment_id=str(preference_id) if preference_id else None,
        status=PaymentStatus.pending,
        amount=float(order.total_amount),
        currency=order.currency,
        init_point=preference.get("init_point"),
        sandbox_init_point=preference.get("sandbox_init_point"),
        idempotency_key=idempotency_key,
        raw_preference=preference,
    )

    db.add(payment)
    order.payment_status = PaymentStatus.pending
    db.add(order)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        reusable_after_race = await _find_reusable_payment(db, order.id, idempotency_key=idempotency_key)
        if not reusable_after_race:
            raise
        return reusable_after_race, False

    await db.refresh(payment)
    await db.refresh(order)
    return payment, True


async def handle_mercado_pago_webhook(
    db: AsyncSession,
    payload: dict,
    *,
    signature_header: str | None = None,
    request_id: str | None = None,
) -> dict:
    if not mercado_pago.validate_webhook_signature(
        payload,
        signature_header=signature_header,
        request_id=request_id,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")

    event_id = _normalize_event_id(payload, request_id)
    event = PaymentWebhookEvent(
        provider=PaymentProvider.mercado_pago,
        event_id=event_id,
        request_id=request_id,
        signature=signature_header,
        payload=payload,
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return {"status": "duplicate"}

    data = payload.get("data") or {}
    payment_id = data.get("id") or payload.get("resource")
    if isinstance(payment_id, str) and "/" in payment_id:
        payment_id = payment_id.rstrip("/").split("/")[-1]
    if not payment_id:
        return {"status": "ignored"}

    stmt = select(Payment.id).where(Payment.provider_payment_id == str(payment_id)).limit(1)
    result = await db.execute(stmt)
    stored_payment_id = result.scalar_one_or_none()
    if not stored_payment_id:
        return {"status": "ignored"}

    payment = await db.get(Payment, stored_payment_id)
    if not payment:
        return {"status": "ignored"}
    order = await order_service.get_order(db, str(payment.order_id))
    event.payment_id = payment.id
    db.add(event)

    try:
        mp_payment = mercado_pago.get_payment(str(payment_id))
    except PaymentProviderError as exc:
        payment.last_webhook = payload
        payment.status_detail = f"error: {exc}"
        db.add(payment)
        await db.flush()
        return {"status": "provider_error"}

    payment_status = _map_mp_status(mp_payment.get("status"))
    payment.status_detail = mp_payment.get("status_detail")
    payment.last_webhook = payload
    payment.provider_payment_id = str(mp_payment.get("id") or payment_id)

    if payment_status == PaymentStatus.approved and order.status != OrderStatus.paid:
        payment.status = payment_status
        await db.flush()
        await order_service.set_status_paid(db, order)
    elif payment_status in [PaymentStatus.refunded, PaymentStatus.partially_refunded]:
        await db.flush()
        provider_amount = mp_payment.get("transaction_amount_refunded")
        refund_delta = None
        if provider_amount is not None:
            provider_total_refunded = _money(float(provider_amount))
            current_refunded = _money(payment.refunded_amount)
            computed_delta = provider_total_refunded - current_refunded
            if computed_delta > 0:
                refund_delta = float(computed_delta)
        await refund_payment(
            db,
            payment,
            reason="provider_webhook",
            amount=refund_delta,
            provider_payload=mp_payment,
            restock_items=False,
        )
    else:
        payment.status = payment_status
        order.payment_status = payment_status
        db.add(order)
        db.add(payment)

    await db.flush()
    await db.refresh(payment)
    return {"status": "processed"}


async def refund_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    amount: float | None = None,
    reason: str | None = None,
    provider_payload: dict | None = None,
    restock_items: bool | None = None,
) -> Payment:
    if payment.status == PaymentStatus.refunded and _money(payment.refunded_amount) >= _money(payment.amount):
        return payment
    if payment.status not in [PaymentStatus.approved, PaymentStatus.partially_refunded]:
        raise ConflictError("Only approved or partially refunded payments can be refunded")
    if not payment.provider_payment_id:
        raise DomainValidationError("Payment has no provider reference")

    order = await order_service.get_order(db, str(payment.order_id))
    if order.status != OrderStatus.paid:
        raise ConflictError("Only paid and unfulfilled orders can be refunded")

    total_amount = _money(payment.amount)
    refunded_amount = _money(payment.refunded_amount)
    remaining_amount = total_amount - refunded_amount
    if remaining_amount <= 0:
        raise ConflictError("Payment has no refundable balance")

    refund_amount = _money(amount) if amount is not None else remaining_amount
    if refund_amount <= 0:
        raise DomainValidationError("Refund amount must be greater than 0")
    if refund_amount > remaining_amount:
        raise ConflictError("Refund amount exceeds refundable balance")

    is_full_refund = refund_amount == remaining_amount
    should_restock = bool(restock_items) if restock_items is not None else is_full_refund
    if should_restock and not is_full_refund:
        raise ConflictError("Partial refunds cannot restock items automatically")

    refund_data = provider_payload
    if refund_data is None:
        try:
            refund_data = mercado_pago.refund_payment(payment.provider_payment_id, amount=float(refund_amount))
        except PaymentProviderConfigurationError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        except PaymentProviderError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if should_restock:
        await db.refresh(order, attribute_names=["lines"])
        for line in order.lines:
            variant = await db.get(ProductVariant, line.variant_id)
            if not variant:
                continue
            await inventory_service.receive_stock(db, variant, line.quantity, reason=f"refund:{order.id}")

    refund_row = PaymentRefund(
        payment=payment,
        amount=float(refund_amount),
        reason=reason,
        provider_refund_id=str(refund_data.get("id")) if refund_data.get("id") else None,
        status_detail=refund_data.get("status_detail"),
        raw_response=refund_data,
    )
    db.add(refund_row)

    new_refunded_total = refunded_amount + refund_amount
    payment.refunded_amount = float(new_refunded_total)
    payment.status = PaymentStatus.refunded if new_refunded_total >= total_amount else PaymentStatus.partially_refunded
    payment.status_detail = refund_data.get("status_detail") or (
        "partially_refunded" if payment.status == PaymentStatus.partially_refunded else "refunded"
    )
    payment.raw_refund = refund_data
    payment.refunded_at = _utcnow() if payment.status == PaymentStatus.refunded else None
    payment.refund_reason = reason
    payment.provider_refund_id = str(refund_data.get("id")) if refund_data.get("id") else payment.provider_refund_id
    db.add(payment)

    order.payment_status = payment.status
    if payment.status == PaymentStatus.refunded:
        order.status = OrderStatus.refunded
        order.refunded_at = payment.refunded_at
    db.add(order)
    await db.flush()

    await notification_service.notify_order_status(
        db,
        order,
        title="Pago reintegrado",
        message=(
            "Tu orden fue reintegrada correctamente."
            if payment.status == PaymentStatus.refunded
            else "Tu orden recibio un reintegro parcial."
        ),
    )
    await db.refresh(payment)
    return payment
