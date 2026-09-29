import hashlib
import hmac
import time
import uuid

import pytest
from httpx import AsyncClient


async def _create_order(client: AsyncClient, admin_token: str, user_token: str):
    r_cat = await client.post(
        "/api/v1/categories",
        json={"name": f"PaymentsCat-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_cat.status_code == 201
    cat = r_cat.json()

    r_brand = await client.post(
        "/api/v1/brands",
        json={"name": f"PaymentsBrand-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_brand.status_code == 201
    brand = r_brand.json()

    r_prod = await client.post(
        "/api/v1/products",
        json={
            "title": "Producto Pagos",
            "price": 2000.0,
            "currency": "ARS",
            "category_id": cat["id"],
            "brand_id": brand["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_prod.status_code == 201
    prod = r_prod.json()

    r_variant = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json={
            "sku": f"PAY-TEST-{uuid.uuid4()}",
            "size_label": "M",
            "color_name": "Rojo",
            "stock_on_hand": 10,
            "active": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_variant.status_code == 201
    variant = r_variant.json()

    ro = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ARS",
            "lines": [
                {"variant_id": variant["id"], "quantity": 1}
            ],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ro.status_code == 201
    return ro.json(), prod, variant


def _build_webhook_signature(secret: str, payment_id: str, request_id: str, ts: int | None = None) -> str:
    ts = ts or int(time.time() * 1000)
    manifest = f"id:{payment_id};request-id:{request_id};ts:{ts};"
    digest = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"ts={ts},v1={digest}"


async def _create_payment(
    client: AsyncClient,
    order_id: str,
    user_token: str,
    monkeypatch,
    *,
    preference_id: str = "pref-123",
):
    fake_pref = {
        "id": preference_id,
        "init_point": "https://mp.test/init",
        "sandbox_init_point": "https://mp.test/sandbox",
    }
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.create_checkout_preference",
        lambda order_obj, idempotency_key=None: fake_pref,
    )
    resp = await client.post(
        f"/api/v1/payments/orders/{order_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), fake_pref


@pytest.mark.asyncio
async def test_payment_preference_creation(client: AsyncClient, admin_token: str, user_token: str, monkeypatch):
    order, _, _ = await _create_order(client, admin_token, user_token)

    payment, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch)
    assert payment["provider"] == "mercado_pago"
    assert payment["init_point"] == fake_pref["init_point"]
    assert payment["status"] == "pending"
    assert payment["refunded_amount"] == 0.0

    order_after = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert order_after.status_code == 200
    data = order_after.json()
    assert data["payment_status"] == "pending"
    assert len(data["payments"]) == 1


@pytest.mark.asyncio
async def test_payment_preference_is_idempotent(client: AsyncClient, admin_token: str, user_token: str, monkeypatch):
    order, _, _ = await _create_order(client, admin_token, user_token)
    calls = {"count": 0}

    def _fake_create(order_obj, idempotency_key=None):
        calls["count"] += 1
        assert idempotency_key == "idem-001"
        return {
            "id": "pref-idem-001",
            "init_point": "https://mp.test/init",
            "sandbox_init_point": "https://mp.test/sandbox",
        }

    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.create_checkout_preference",
        _fake_create,
    )

    first = await client.post(
        f"/api/v1/payments/orders/{order['id']}",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "idem-001",
        },
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/v1/payments/orders/{order['id']}",
        headers={
            "Authorization": f"Bearer {user_token}",
            "Idempotency-Key": "idem-001",
        },
    )
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert calls["count"] == 1

    order_after = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert order_after.status_code == 200
    assert len(order_after.json()["payments"]) == 1


@pytest.mark.asyncio
async def test_payment_webhook_updates_order_with_valid_signature(
    client: AsyncClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    order, _, _ = await _create_order(client, admin_token, user_token)
    _, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch, preference_id="pref-456")

    monkeypatch.setattr("app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.get_payment",
        lambda payment_id: {
            "id": payment_id,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": order["id"],
            "transaction_amount": order["total_amount"],
            "currency_id": order["currency"],
        },
    )

    request_id = "req-valid-001"
    webhook_resp = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers={
            "x-request-id": request_id,
            "x-signature": _build_webhook_signature("whsec-test", fake_pref["id"], request_id),
        },
    )
    assert webhook_resp.status_code == 200, webhook_resp.text
    assert webhook_resp.json()["status"] == "processed"

    order_after = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert order_after.status_code == 200
    data = order_after.json()
    assert data["status"] == "paid"
    assert data["payment_status"] == "approved"


@pytest.mark.asyncio
async def test_payment_webhook_rejects_invalid_signature(
    client: AsyncClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    order, _, _ = await _create_order(client, admin_token, user_token)
    _, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch, preference_id="pref-invalid-signature")

    monkeypatch.setattr("app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")

    webhook_resp = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers={
            "x-request-id": "req-invalid-001",
            "x-signature": "ts=1,v1=invalid",
        },
    )
    assert webhook_resp.status_code == 401, webhook_resp.text
    assert webhook_resp.json()["detail"] == "Invalid webhook signature"


@pytest.mark.asyncio
async def test_payment_webhook_is_deduplicated(
    client: AsyncClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    order, _, _ = await _create_order(client, admin_token, user_token)
    _, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch, preference_id="pref-duplicate")
    monkeypatch.setattr("app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")

    calls = {"count": 0}

    def _fake_get_payment(payment_id):
        calls["count"] += 1
        return {
            "id": payment_id,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": order["id"],
            "transaction_amount": order["total_amount"],
            "currency_id": order["currency"],
        }

    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.get_payment",
        _fake_get_payment,
    )

    request_id = "req-duplicate-001"
    headers = {
        "x-request-id": request_id,
        "x-signature": _build_webhook_signature("whsec-test", fake_pref["id"], request_id),
    }

    first = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed"

    second = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_payment_refund_updates_payment_and_order(
    client: AsyncClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    order, product, variant = await _create_order(client, admin_token, user_token)
    payment, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch, preference_id="pref-refund")

    monkeypatch.setattr("app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.get_payment",
        lambda payment_id: {
            "id": payment_id,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": order["id"],
            "transaction_amount": order["total_amount"],
            "currency_id": order["currency"],
        },
    )

    request_id = "req-refund-approve-001"
    approve = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers={
            "x-request-id": request_id,
            "x-signature": _build_webhook_signature("whsec-test", fake_pref["id"], request_id),
        },
    )
    assert approve.status_code == 200, approve.text

    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.refund_payment",
        lambda payment_id, amount=None, idempotency_key=None: {
            "id": f"refund-{payment_id}",
            "status": "approved",
            "status_detail": "refunded",
        },
    )

    refund = await client.post(
        f"/api/v1/payments/{payment['id']}/refund",
        json={"reason": "customer_request"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert refund.status_code == 200, refund.text
    refunded = refund.json()
    assert refunded["status"] == "refunded"
    assert refunded["refund_reason"] == "customer_request"
    assert refunded["refunded_at"] is not None
    assert refunded["refunded_amount"] == 2000.0

    order_after = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert order_after.status_code == 200
    data = order_after.json()
    assert data["status"] == "refunded"
    assert data["payment_status"] == "refunded"
    assert data["refunded_at"] is not None

    product_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert product_resp.status_code == 200
    variant_after = product_resp.json()["variants"][0]
    assert variant_after["stock_on_hand"] == 10


@pytest.mark.asyncio
async def test_payment_partial_refund_updates_balance_and_audit(
    client: AsyncClient,
    admin_token: str,
    user_token: str,
    monkeypatch,
):
    order, product, _ = await _create_order(client, admin_token, user_token)
    payment, fake_pref = await _create_payment(client, order["id"], user_token, monkeypatch, preference_id="pref-partial-refund")

    monkeypatch.setattr("app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.get_payment",
        lambda payment_id: {
            "id": payment_id,
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": order["id"],
            "transaction_amount": order["total_amount"],
            "currency_id": order["currency"],
        },
    )

    approve_request_id = "req-partial-approve-001"
    approve = await client.post(
        f"/api/v1/payments/mercado-pago/webhook?data.id={fake_pref['id']}",
        json={"data": {"id": fake_pref["id"]}},
        headers={
            "x-request-id": approve_request_id,
            "x-signature": _build_webhook_signature("whsec-test", fake_pref["id"], approve_request_id),
        },
    )
    assert approve.status_code == 200, approve.text

    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.refund_payment",
        lambda payment_id, amount=None, idempotency_key=None: {
            "id": f"refund-{payment_id}-partial",
            "status": "approved",
            "status_detail": "partial_refund",
            "amount": amount,
        },
    )

    refund = await client.post(
        f"/api/v1/payments/{payment['id']}/refund",
        json={"amount": 500.0, "reason": "coupon_adjustment"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert refund.status_code == 200, refund.text
    partial = refund.json()
    assert partial["status"] == "partially_refunded"
    assert partial["refunded_amount"] == 500.0
    assert partial["refunded_at"] is None

    order_after = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert order_after.status_code == 200
    order_data = order_after.json()
    assert order_data["status"] == "paid"
    assert order_data["payment_status"] == "partially_refunded"
    assert order_data["refunded_at"] is None

    product_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert product_resp.status_code == 200
    variant_after = product_resp.json()["variants"][0]
    assert variant_after["stock_on_hand"] == 9

    audit = await client.get(
        f"/api/v1/payments/{payment['id']}/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200, audit.text
    audit_data = audit.json()
    assert audit_data["payment"]["id"] == payment["id"]
    assert audit_data["payment"]["status"] == "partially_refunded"
    assert audit_data["payment"]["refunded_amount"] == 500.0
    assert len(audit_data["refunds"]) == 1
    assert audit_data["refunds"][0]["amount"] == 500.0
    assert audit_data["refunds"][0]["reason"] == "coupon_adjustment"
    assert len(audit_data["webhook_events"]) == 1


@pytest.mark.asyncio
async def test_admin_cannot_create_customer_payment(client: AsyncClient, admin_token: str, user_token: str, monkeypatch):
    order, _, _ = await _create_order(client, admin_token, user_token)

    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.create_checkout_preference",
        lambda order_obj, idempotency_key=None: {
            "id": "pref-admin-blocked",
            "init_point": "https://mp.test/init",
            "sandbox_init_point": "https://mp.test/sandbox",
        },
    )

    resp = await client.post(
        f"/api/v1/payments/orders/{order['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Admin users cannot create customer payments"


@pytest.mark.asyncio
async def test_webhook_rejects_missing_query_signature_and_stale_timestamp(
    client: AsyncClient, monkeypatch
):
    from app.services.payment_providers import mercado_pago

    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_WEBHOOK_SECRET", "whsec-test")
    request_id = "negative-webhook"
    payment_id = "PAY01ABC"
    payload = {"data": {"id": payment_id}}
    url = f"/api/v1/payments/mercado-pago/webhook?data.id={payment_id}"
    valid = _build_webhook_signature("whsec-test", payment_id.lower(), request_id)

    assert (await client.post(url, json=payload)).status_code == 401
    assert (
        await client.post(
            "/api/v1/payments/mercado-pago/webhook",
            json=payload,
            headers={"x-request-id": request_id, "x-signature": valid},
        )
    ).status_code == 401
    assert (
        await client.post(
            url,
            json={"data": {"id": "OTHER"}},
            headers={"x-request-id": request_id, "x-signature": valid},
        )
    ).status_code == 400
    stale = _build_webhook_signature(
        "whsec-test", payment_id.lower(), request_id, ts=int((time.time() - 3600) * 1000)
    )
    assert (
        await client.post(
            url,
            json=payload,
            headers={"x-request-id": request_id, "x-signature": stale},
        )
    ).status_code == 401
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_WEBHOOK_SECRET", None)
    assert (
        await client.post(
            url,
            json=payload,
            headers={"x-request-id": request_id, "x-signature": valid},
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_webhook_wrong_order_and_out_of_order_event(
    client: AsyncClient, admin_token: str, user_token: str, monkeypatch
):
    order, _, _ = await _create_order(client, admin_token, user_token)
    payment, _ = await _create_payment(
        client, order["id"], user_token, monkeypatch, preference_id="provider-payment-789"
    )
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.settings.MERCADO_PAGO_WEBHOOK_SECRET",
        "whsec-test",
    )
    provider_state = {
        "id": "provider-payment-789",
        "status": "approved",
        "external_reference": str(uuid.uuid4()),
        "transaction_amount": order["total_amount"],
        "currency_id": order["currency"],
    }
    monkeypatch.setattr(
        "app.services.payment_providers.mercado_pago.get_payment", lambda _: provider_state
    )

    async def send(request_id):
        return await client.post(
            "/api/v1/payments/mercado-pago/webhook?data.id=provider-payment-789",
            json={"data": {"id": "provider-payment-789"}},
            headers={
                "x-request-id": request_id,
                "x-signature": _build_webhook_signature(
                    "whsec-test", "provider-payment-789", request_id
                ),
            },
        )

    assert (await send("wrong-order")).status_code in (404, 409)
    provider_state["external_reference"] = order["id"]
    assert (await send("approved-event")).json()["status"] == "processed"
    provider_state["status"] = "pending"
    assert (await send("late-pending-event")).json()["status"] == "stale"
    audit = await client.get(
        f"/api/v1/payments/{payment['id']}/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    assert sorted(event["outcome"] for event in audit.json()["webhook_events"]) == [
        "processed", "stale"
    ]
    assert all(event.get("signature") is None for event in audit.json()["webhook_events"])


def test_provider_distinguishes_retryable_and_permanent_http_errors(monkeypatch):
    import httpx

    from app.services.payment_providers import (
        PaymentProviderPermanentError,
        PaymentProviderTransientError,
        mercado_pago,
    )

    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", "test-token")
    request = httpx.Request("GET", "https://api.mercadopago.com/v1/payments/123")
    for code, expected in ((400, PaymentProviderPermanentError), (429, PaymentProviderTransientError), (503, PaymentProviderTransientError)):
        monkeypatch.setattr(
            mercado_pago.httpx, "get", lambda *args, code=code, **kwargs: httpx.Response(code, request=request)
        )
        with pytest.raises(expected):
            mercado_pago.get_payment("123")
