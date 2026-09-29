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
    PaymentProviderPermanentError,
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
    order = await db.get(Order, order.id, with_for_update=True, populate_existing=True)
    await db.refresh(order, attribute_names=["lines"])
    if order.status not in [OrderStatus.pending_payment, OrderStatus.draft]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order is not ready to pay")
    if not order.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order has no items")

    reusable = await _find_reusable_payment(db, order.id, idempotency_key=idempotency_key)
    if reusable:
        await db.refresh(reusable)
        return reusable, False

    try:
        preference = await mercado_pago.create_checkout_preference(order, idempotency_key=idempotency_key)
    except PaymentProviderConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payment provider is not configured") from exc
    except PaymentProviderPermanentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payment provider rejected preference") from exc
    except PaymentProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Payment provider temporarily unavailable") from exc

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
        raw_preference=None,
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
    resource_id: str | None = None,
) -> dict:
    if not mercado_pago.validate_webhook_signature(
        resource_id,
        signature_header=signature_header,
        request_id=request_id,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")

    data = payload.get("data") or {}
    if str(data.get("id", "")).lower() != str(resource_id).lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Webhook resource mismatch")

    event_id = _normalize_event_id(payload, request_id)
    event = PaymentWebhookEvent(
        provider=PaymentProvider.mercado_pago,
        event_id=event_id,
        request_id=request_id,
        event_type=str(payload.get("type") or payload.get("action") or "payment")[:80],
        outcome="received",
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return {"status": "duplicate"}

    try:
        mp_payment = await mercado_pago.get_payment(str(resource_id))
    except PaymentProviderPermanentError:
        event.outcome = "ignored"
        await db.flush()
        return {"status": "ignored"}
    except PaymentProviderError as exc:
        # Roll back the event too; Mercado Pago must be able to retry it.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Payment provider temporarily unavailable") from exc

    if str(mp_payment.get("id")) != str(resource_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider payment identifier mismatch")
    try:
        referenced_order_id = uuid.UUID(str(mp_payment.get("external_reference")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider order reference mismatch") from exc
    order = await order_service.get_order(db, str(referenced_order_id))
    if (
        _money(mp_payment.get("transaction_amount")) != _money(order.total_amount)
        or mp_payment.get("currency_id") != order.currency
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider payment amount or currency mismatch")

    payment = await db.scalar(
        select(Payment)
        .where(Payment.order_id == order.id)
        .where(Payment.provider == PaymentProvider.mercado_pago)
        .order_by(Payment.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if payment is None or _money(payment.amount) != _money(order.total_amount):
        raise HTTPException(status.HTTP_409_CONFLICT, "No matching payment for order")
    if (
        payment.status not in (PaymentStatus.pending, PaymentStatus.authorized)
        and payment.provider_payment_id != str(resource_id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider payment identifier mismatch")
    event.payment_id = payment.id
    payment.provider_payment_id = str(resource_id)

    payment_status = _map_mp_status(mp_payment.get("status"))
    if payment.status in (
        PaymentStatus.approved,
        PaymentStatus.partially_refunded,
        PaymentStatus.refunded,
    ) and payment_status in (
        PaymentStatus.pending,
        PaymentStatus.authorized,
        PaymentStatus.rejected,
        PaymentStatus.cancelled,
    ):
        event.outcome = "stale"
        await db.flush()
        return {"status": "stale"}
    if payment.status == PaymentStatus.refunded and payment_status == PaymentStatus.approved:
        event.outcome = "stale"
        await db.flush()
        return {"status": "stale"}
    payment.status_detail = str(mp_payment.get("status_detail") or "")[:120] or None

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
    event.outcome = "processed"
    return {"status": "processed"}


async def refund_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    amount: float | None = None,
    reason: str | None = None,
    provider_payload: dict | None = None,
    restock_items: bool | None = None,
    idempotency_key: str | None = None,
) -> Payment:
    payment = await db.get(Payment, payment.id, with_for_update=True, populate_existing=True)
    if idempotency_key:
        prior = await db.scalar(
            select(PaymentRefund).where(
                PaymentRefund.payment_id == payment.id,
                PaymentRefund.idempotency_key == idempotency_key,
            )
        )
        if prior is not None:
            if (amount is not None and _money(amount) != _money(prior.amount)) or prior.reason != reason:
                raise ConflictError("Idempotency key was used for a different refund")
            return payment
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
            refund_data = await mercado_pago.refund_payment(
                payment.provider_payment_id,
                amount=float(refund_amount),
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
        except PaymentProviderConfigurationError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payment provider is not configured") from exc
        except PaymentProviderPermanentError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payment provider rejected refund") from exc
        except PaymentProviderError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Payment provider temporarily unavailable") from exc

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
        idempotency_key=idempotency_key,
        status_detail=refund_data.get("status_detail"),
        raw_response=None,
    )
    db.add(refund_row)

    new_refunded_total = refunded_amount + refund_amount
    payment.refunded_amount = float(new_refunded_total)
    payment.status = PaymentStatus.refunded if new_refunded_total >= total_amount else PaymentStatus.partially_refunded
    payment.status_detail = refund_data.get("status_detail") or (
        "partially_refunded" if payment.status == PaymentStatus.partially_refunded else "refunded"
    )
    payment.raw_refund = None
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
