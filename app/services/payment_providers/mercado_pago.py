from __future__ import annotations

import hashlib
import hmac
import time

import httpx

from app.core.config import settings
from app.models.order import Order
from app.services.payment_providers import (
    PaymentProviderConfigurationError,
    PaymentProviderPermanentError,
    PaymentProviderTransientError,
)


API_BASE_URL = "https://api.mercadopago.com"


def _raise_provider_status(exc: httpx.HTTPStatusError) -> None:
    if exc.response.status_code == 429 or exc.response.status_code >= 500:
        raise PaymentProviderTransientError("Mercado Pago temporarily unavailable") from exc
    raise PaymentProviderPermanentError("Mercado Pago rejected the request") from exc


def _get_access_token() -> str:
    token = settings.MERCADO_PAGO_ACCESS_TOKEN
    if not token:
        raise PaymentProviderConfigurationError("Mercado Pago access token is not configured")
    return token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }


async def create_checkout_preference(order: Order, *, idempotency_key: str | None = None) -> dict:
    items = [
        {
            "id": str(line.variant_id),
            "title": f"SKU {line.variant_id}",
            "quantity": int(line.quantity),
            "currency_id": order.currency,
            "unit_price": float(line.unit_price),
        }
        for line in order.lines
    ]

    payload = {
        "external_reference": str(order.id),
        "items": items,
        "back_urls": {
            "success": settings.MERCADO_PAGO_SUCCESS_URL,
            "failure": settings.MERCADO_PAGO_FAILURE_URL,
            "pending": settings.MERCADO_PAGO_PENDING_URL,
        },
        "auto_return": "approved",
        "metadata": {
            "order_id": str(order.id),
            "project": settings.PROJECT_NAME,
        },
    }

    if settings.MERCADO_PAGO_NOTIFICATION_URL:
        payload["notification_url"] = settings.MERCADO_PAGO_NOTIFICATION_URL

    try:
        headers = _headers()
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{API_BASE_URL}/checkout/preferences", json=payload, headers=headers
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_provider_status(exc)
    except httpx.HTTPError as exc:
        raise PaymentProviderTransientError("Mercado Pago connection failed") from exc

    return response.json()


async def refund_payment(
    payment_id: str, *, amount: float | None = None, idempotency_key: str
) -> dict:
    payload = {"amount": amount} if amount is not None else None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{API_BASE_URL}/v1/payments/{payment_id}/refunds",
                json=payload,
                headers={**_headers(), "X-Idempotency-Key": idempotency_key},
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_provider_status(exc)
    except httpx.HTTPError as exc:
        raise PaymentProviderTransientError("Mercado Pago connection failed") from exc

    return response.json()


async def get_payment(payment_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{API_BASE_URL}/v1/payments/{payment_id}", headers=_headers()
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_provider_status(exc)
    except httpx.HTTPError as exc:
        raise PaymentProviderTransientError("Mercado Pago connection failed") from exc

    return response.json()


def validate_webhook_signature(
    resource_id: str | None,
    *,
    signature_header: str | None,
    request_id: str | None,
    tolerance_seconds: int | None = None,
) -> bool:
    secret = settings.MERCADO_PAGO_WEBHOOK_SECRET
    if not secret:
        return False
    if not signature_header or not request_id or not resource_id:
        return False

    signature_parts: dict[str, str] = {}
    for fragment in signature_header.split(","):
        if "=" not in fragment:
            continue
        key, value = fragment.split("=", 1)
        signature_parts[key.strip()] = value.strip()

    ts = signature_parts.get("ts")
    provided_v1 = signature_parts.get("v1")
    if not ts or not provided_v1:
        return False

    try:
        ts_int = int(ts)
    except ValueError:
        return False

    max_age = tolerance_seconds or settings.MERCADO_PAGO_WEBHOOK_TOLERANCE_SECONDS
    timestamp_seconds = ts_int / 1000 if ts_int >= 10**12 else ts_int
    if max_age > 0 and abs(time.time() - timestamp_seconds) > max_age:
        return False
    manifest = f"id:{resource_id.lower()};request-id:{request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode("utf-8"),
        msg=manifest.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected.lower(), provided_v1.lower())
