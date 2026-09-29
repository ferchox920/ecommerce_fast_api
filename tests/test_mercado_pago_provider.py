"""Mercado Pago's HTTP contract, exercised without network traffic."""

import inspect
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.payment_providers import (
    PaymentProviderConfigurationError,
    PaymentProviderPermanentError,
    PaymentProviderTransientError,
    mercado_pago,
)

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


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
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "pref-1", "init_point": "https://example.test/pay"})

    timeouts = _transport_client(monkeypatch, respond)
    line = SimpleNamespace(variant_id="variant-1", quantity=2, unit_price=12.5)
    order = SimpleNamespace(id="order-1", currency="ARS", lines=[line])
    assert inspect.iscoroutinefunction(mercado_pago.create_checkout_preference)
    result = await mercado_pago.create_checkout_preference(order, idempotency_key="preference-key")
    assert result["id"] == "pref-1"
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/checkout/preferences"
    assert seen[0].headers["X-Idempotency-Key"] == "preference-key"
    assert seen[0].headers["Authorization"] == "Bearer local-test-token"
    payload = json.loads(seen[0].content)
    assert payload["external_reference"] == "order-1"
    assert payload["items"] == [{"id": "variant-1", "title": "SKU variant-1", "quantity": 2, "currency_id": "ARS", "unit_price": 12.5}]
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
