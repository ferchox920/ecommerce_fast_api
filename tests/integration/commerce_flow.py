"""Commercial API flow on the migrated PostgreSQL database and live Redis."""

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.core.security import get_password_hash
from app.db.session_async import AsyncSessionLocal
from app.db.session_async import async_engine
from app.main import app
from app.models.inventory import InventoryMovement
from app.models.notification import Notification, NotificationType
from app.models.product import ProductVariant
from app.models.user import User
from app.services.payment_providers import mercado_pago


@pytest.mark.asyncio
async def test_commerce_api_flow_with_provider_double(monkeypatch):
    assert os.environ["ASYNC_DATABASE_URL"].startswith("postgresql+asyncpg://")
    suffix = uuid.uuid4()
    admin = User(
        email=f"flow-admin-{suffix}@example.com",
        hashed_password=get_password_hash("Admin1234"),
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    buyer = User(
        email=f"flow-buyer-{suffix}@example.com",
        hashed_password=get_password_hash("Buyer1234"),
        is_active=True,
        email_verified=True,
    )
    stranger = User(
        email=f"flow-stranger-{suffix}@example.com",
        hashed_password=get_password_hash("Stranger1234"),
        is_active=True,
        email_verified=True,
    )
    async with AsyncSessionLocal() as session:
        session.add_all([admin, buyer, stranger])
        await session.commit()
        buyer_id = buyer.id

    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_WEBHOOK_SECRET", "flow-local-secret")
    provider_payment_id = f"payment-{uuid.uuid4()}"
    monkeypatch.setattr(
        mercado_pago,
        "create_checkout_preference",
        lambda order, idempotency_key=None: {
            "id": f"preference-{uuid.uuid4()}",
            "init_point": "https://example.test/checkout",
        },
    )
    provider_state = {}
    monkeypatch.setattr(mercado_pago, "get_payment", lambda payment_id: provider_state)
    refund_calls = []

    def fake_refund(payment_id, *, amount, idempotency_key):
        refund_calls.append((payment_id, amount, idempotency_key))
        return {"id": f"refund-{idempotency_key}", "status_detail": "approved"}

    monkeypatch.setattr(mercado_pago, "refund_payment", fake_refund)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        async def login(email, password):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": email, "password": password},
            )
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['access_token']}"}

        admin_headers = await login(admin.email, "Admin1234")
        buyer_headers = await login(buyer.email, "Buyer1234")
        stranger_headers = await login(stranger.email, "Stranger1234")

        category = await client.post(
            "/api/v1/categories", json={"name": f"FlowCat-{suffix}"}, headers=admin_headers
        )
        assert category.status_code == 201, category.text
        brand = await client.post(
            "/api/v1/brands", json={"name": f"FlowBrand-{suffix}"}, headers=admin_headers
        )
        assert brand.status_code == 201, brand.text
        product = await client.post(
            "/api/v1/products",
            json={
                "title": f"FlowProduct-{suffix}",
                "price": 2000,
                "currency": "ARS",
                "category_id": category.json()["id"],
                "brand_id": brand.json()["id"],
            },
            headers=admin_headers,
        )
        assert product.status_code == 201, product.text
        variant = await client.post(
            f"/api/v1/products/{product.json()['id']}/variants",
            json={
                "sku": f"FLOW-{suffix}",
                "size_label": "M",
                "color_name": "Black",
                "stock_on_hand": 0,
            },
            headers=admin_headers,
        )
        assert variant.status_code == 201, variant.text
        variant_id = variant.json()["id"]
        receive = await client.post(
            f"/api/v1/products/variants/{variant_id}/stock/receive",
            json={"type": "receive", "quantity": 2, "reason": "flow setup"},
            headers=admin_headers,
        )
        assert receive.status_code == 200, receive.text

        cart = await client.post("/api/v1/cart", json={"currency": "ARS"}, headers=buyer_headers)
        assert cart.status_code == 201, cart.text
        item = await client.post(
            "/api/v1/cart/items",
            json={"variant_id": variant_id, "quantity": 1},
            headers=buyer_headers,
        )
        assert item.status_code == 201, item.text
        now = datetime.now(timezone.utc)
        promotion = await client.post(
            "/api/v1/admin/promotions",
            json={
                "name": f"FlowPromotion-{suffix}",
                "type": "product",
                "scope": "product",
                "criteria": {"product_ids": [product.json()["id"]]},
                "benefits": {"discount_percent": 10},
                "start_at": (now - timedelta(minutes=1)).isoformat(),
                "end_at": (now + timedelta(hours=1)).isoformat(),
            },
            headers=admin_headers,
        )
        assert promotion.status_code == 201, promotion.text
        promotion_id = promotion.json()["id"]
        activate = await client.post(
            f"/api/v1/admin/promotions/{promotion_id}/activate", headers=admin_headers
        )
        assert activate.status_code == 200, activate.text
        order = await client.post(
            "/api/v1/orders/from-cart",
            json={"promotion_id": promotion_id},
            headers=buyer_headers,
        )
        assert order.status_code == 201, order.text
        order_id = order.json()["id"]
        assert order.json()["total_amount"] == 1800
        assert order.json()["discount_amount"] == 200
        assert order.json()["applied_promotion_id"] == promotion_id
        assert (
            await client.get(f"/api/v1/orders/{order_id}", headers=stranger_headers)
        ).status_code == 404

        payment = await client.post(
            f"/api/v1/payments/orders/{order_id}",
            headers={**buyer_headers, "Idempotency-Key": f"pay-{suffix}"},
        )
        assert payment.status_code == 201, payment.text
        payment_id = payment.json()["id"]
        provider_state.update({
            "id": provider_payment_id,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": order_id,
            "transaction_amount": 1800,
            "currency_id": "ARS",
        })
        request_id = f"flow-{suffix}"
        ts = int(time.time() * 1000)
        manifest = f"id:{provider_payment_id};request-id:{request_id};ts:{ts};"
        signature = hmac.new(
            b"flow-local-secret", manifest.encode(), hashlib.sha256
        ).hexdigest()
        webhook_args = {
            "json": {"type": "payment", "data": {"id": provider_payment_id}},
            "headers": {"x-request-id": request_id, "x-signature": f"ts={ts},v1={signature}"},
        }
        webhook_url = f"/api/v1/payments/mercado-pago/webhook?data.id={provider_payment_id}"
        first_webhook = await client.post(webhook_url, **webhook_args)
        assert first_webhook.status_code == 200, first_webhook.text
        assert first_webhook.json()["status"] == "processed"
        replay = await client.post(webhook_url, **webhook_args)
        assert replay.status_code == 200, replay.text
        assert replay.json()["status"] == "duplicate"
        paid = await client.get(f"/api/v1/orders/{order_id}", headers=buyer_headers)
        assert paid.json()["status"] == "paid"

        refund = await client.post(
            f"/api/v1/payments/{payment_id}/refund",
            json={"amount": 500, "reason": "flow"},
            headers={**admin_headers, "Idempotency-Key": f"refund-{suffix}"},
        )
        assert refund.status_code == 200, refund.text
        refund_replay = await client.post(
            f"/api/v1/payments/{payment_id}/refund",
            json={"amount": 500, "reason": "flow"},
            headers={**admin_headers, "Idempotency-Key": f"refund-{suffix}"},
        )
        assert refund_replay.status_code == 200, refund_replay.text
        assert refund_replay.json()["refunded_amount"] == 500
        assert len(refund_calls) == 1

    async with AsyncSessionLocal() as verify:
        stored_variant = await verify.get(ProductVariant, uuid.UUID(variant_id))
        assert (stored_variant.stock_on_hand, stored_variant.stock_reserved) == (1, 0)
        assert await verify.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.variant_id == stored_variant.id
            )
        ) == 3
        assert await verify.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == buyer_id,
                Notification.type == NotificationType.order_status,
            )
        ) >= 2
    await async_engine.dispose()
