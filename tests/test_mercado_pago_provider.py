"""Mercado Pago's HTTP contract, exercised without network traffic."""

import inspect
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.models.order import OrderLine

from app.services.payment_providers import (
    PaymentProviderConfigurationError,
    PaymentProviderPermanentError,
    PaymentProviderTransientError,
    mercado_pago,
)

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize("subtotal,discount,shipping,tax,total,quantity,price", [
    ("25.00", "0", "0", "0", "25.00", 2, "12.50"),
    ("25.00", "2.50", "0", "0", "22.50", 2, "12.50"),
    ("25.00", "0", "1.21", "0.79", "27.00", 2, "12.50"),
    ("25.00", "2.50", "1.21", "0.79", "24.50", 2, "12.50"),
    ("0.87", "0.07", "0.11", "0.02", "0.93", 3, "0.29"),
])
async def test_preference_amount_matches_authorized_total(monkeypatch, subtotal, discount, shipping, tax, total, quantity, price):
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", "local-test-token")
    seen = []
    def respond(request):
        seen.append(json.loads(request.content, parse_float=Decimal))
        return httpx.Response(201, json={"id": "pref-amount"})
    _transport_client(monkeypatch, respond)
    line = OrderLine(variant_id=uuid.uuid4(), quantity=quantity, unit_price=Decimal(price),
                     line_total=Decimal(subtotal), sku_snapshot="SKU-OLD",
                     product_title_snapshot="Original title at purchase")
    order = SimpleNamespace(id="order-amount", currency="ARS", lines=[line], subtotal_amount=Decimal(subtotal), discount_amount=Decimal(discount), shipping_amount=Decimal(shipping), tax_amount=Decimal(tax), total_amount=Decimal(total))
    await mercado_pago.create_checkout_preference(order, idempotency_key="amount-key")
    payload = seen[0]
    assert sum(Decimal(str(item["unit_price"])) * item["quantity"] for item in payload["items"]) == Decimal(total)
    assert all(item["currency_id"] == order.currency for item in payload["items"])
    assert payload["metadata"]["order_lines"][0] == {
        "variant_id": str(line.variant_id), "sku": "SKU-OLD",
        "title": "Original title at purchase", "quantity": quantity,
        "unit_price": price,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("total", ["0", "-0.01", "NaN", "Infinity", "0.001"])
async def test_non_payable_total_rejected_before_http(monkeypatch, total):
    def unexpected(request):
        pytest.fail("Non-payable total must never reach provider HTTP")
    _transport_client(monkeypatch, unexpected)
    order = SimpleNamespace(id="bad-order", currency="ARS", total_amount=Decimal(total), lines=[])
    with pytest.raises(PaymentProviderPermanentError, match="payable"):
        await mercado_pago.create_checkout_preference(order)


def _transport_client(monkeypatch, handler):
    observed = []

    def make_client(*, timeout):
        observed.append(timeout)
        return ORIGINAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(mercado_pago.httpx, "AsyncClient", make_client)
    return observed


@pytest.mark.asyncio
async def test_preference_awaits_http_and_preserves_checkout_contract(monkeypatch):
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", "local-test-token")
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_API_BASE_URL", "http://127.0.0.1:59001")
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "pref-1", "init_point": "https://example.test/pay"})

    timeouts = _transport_client(monkeypatch, respond)
    line = SimpleNamespace(variant_id="variant-1", quantity=2, unit_price=12.5)
    order = SimpleNamespace(id="order-1", currency="ARS", total_amount=Decimal("25.00"), lines=[line])
    assert inspect.iscoroutinefunction(mercado_pago.create_checkout_preference)
    result = await mercado_pago.create_checkout_preference(order, idempotency_key="preference-key")
    assert result["id"] == "pref-1"
    assert seen[0].method == "POST"
    assert seen[0].url.host == "127.0.0.1"
    assert seen[0].url.path == "/checkout/preferences"
    assert seen[0].headers["X-Idempotency-Key"] == "preference-key"
    assert seen[0].headers["Authorization"] == "Bearer local-test-token"
    payload = json.loads(seen[0].content)
    assert payload["external_reference"] == "order-1"
    assert payload["items"] == [{"id": "order-1", "title": "Pedido order-1", "quantity": 1, "currency_id": "ARS", "unit_price": 25.0}]
    assert timeouts == [15.0]


@pytest.mark.asyncio
async def test_payment_lookup_and_refund_use_async_http(monkeypatch):
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", "local-test-token")
    seen = []

    def respond(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "payment-1", "status": "approved"})
        return httpx.Response(201, json={"id": "refund-1", "status": "approved"})

    timeouts = _transport_client(monkeypatch, respond)
    assert inspect.iscoroutinefunction(mercado_pago.get_payment)
    assert inspect.iscoroutinefunction(mercado_pago.refund_payment)
    assert (await mercado_pago.get_payment("payment-1"))["status"] == "approved"
    assert (await mercado_pago.refund_payment("payment-1", amount=7.5, idempotency_key="refund-key"))["id"] == "refund-1"
    assert seen[0].url.path == "/v1/payments/payment-1"
    assert seen[1].url.path == "/v1/payments/payment-1/refunds"
    assert seen[1].headers["X-Idempotency-Key"] == "refund-key"
    assert json.loads(seen[1].content) == {"amount": 7.5}
    assert timeouts == [15.0, 15.0]


@pytest.mark.asyncio
async def test_provider_error_classification_and_connection_failure(monkeypatch):
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", "local-test-token")
    for code, expected in ((400, PaymentProviderPermanentError), (429, PaymentProviderTransientError), (500, PaymentProviderTransientError)):
        _transport_client(monkeypatch, lambda request, code=code: httpx.Response(code))
        with pytest.raises(expected):
            await mercado_pago.get_payment("payment-1")

    def disconnect(request):
        raise httpx.ConnectError("local simulated failure", request=request)

    _transport_client(monkeypatch, disconnect)
    with pytest.raises(PaymentProviderTransientError):
        await mercado_pago.get_payment("payment-1")


@pytest.mark.asyncio
async def test_missing_token_is_configuration_error(monkeypatch):
    monkeypatch.setattr(mercado_pago.settings, "MERCADO_PAGO_ACCESS_TOKEN", None)
    with pytest.raises(PaymentProviderConfigurationError):
        await mercado_pago.get_payment("payment-1")
