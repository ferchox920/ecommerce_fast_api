"""Refund serialization using independent PostgreSQL transactions."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentProvider,
    PaymentRefund,
    PaymentStatus,
)
from app.services import payment_service
from app.services.exceptions import ConflictError


@pytest.mark.asyncio
async def test_two_refunds_cannot_exceed_paid_amount(monkeypatch):
    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    calls = []

    async def fake_refund(payment_id, *, amount, idempotency_key):
        calls.append((amount, idempotency_key))
        return {"id": f"refund-{idempotency_key}", "status_detail": "approved"}

    monkeypatch.setattr(payment_service.mercado_pago, "refund_payment", fake_refund)
    try:
        async with sessions() as setup:
            order = Order(
                status=OrderStatus.paid,
                payment_status=PaymentStatus.approved,
                currency="ARS",
                subtotal_amount=100,
                total_amount=100,
            )
            setup.add(order)
            await setup.flush()
            payment = Payment(
                order_id=order.id,
                provider=PaymentProvider.mercado_pago,
                provider_payment_id=f"payment-{uuid.uuid4()}",
                status=PaymentStatus.approved,
                amount=100,
                currency="ARS",
                refunded_amount=0,
            )
            setup.add(payment)
            await setup.commit()
            payment_id = payment.id

        async def refund(key):
            async with sessions() as session:
                payment = await session.get(Payment, payment_id)
                try:
                    await payment_service.refund_payment(
                        session, payment, amount=70, reason="test", idempotency_key=key
                    )
                    await session.commit()
                    return "refunded"
                except ConflictError:
                    await session.rollback()
                    return "rejected"

        assert sorted(await asyncio.gather(refund("a"), refund("b"))) == [
            "refunded", "rejected"
        ]
        assert await refund(calls[0][1]) == "refunded"
        assert len(calls) == 1
        async with sessions() as verify:
            stored = await verify.get(Payment, payment_id)
            assert stored.refunded_amount == 70
            assert await verify.scalar(
                select(func.count(PaymentRefund.id)).where(PaymentRefund.payment_id == payment_id)
            ) == 1
    finally:
        await engine.dispose()
