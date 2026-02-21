from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.schemas.auth import OAuthProviderConfig


class OAuthValidationError(Exception):
    pass


async def verify_provider_id_token(provider: str, id_token: str) -> dict[str, object]:
    provider_normalized = provider.strip().lower()
    if provider_normalized == "google":
        return await _verify_google_id_token(id_token)
    raise OAuthValidationError("Unsupported OAuth provider")


def get_oauth_frontend_providers() -> list[OAuthProviderConfig]:
    providers: list[OAuthProviderConfig] = []
    if settings.GOOGLE_OAUTH_CLIENT_ID:
        providers.append(
            OAuthProviderConfig(
                provider="google",
                client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            )
        )
    return providers


async def _verify_google_id_token(id_token: str) -> dict[str, object]:
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise OAuthValidationError("Google OAuth is not configured")

    url = "https://oauth2.googleapis.com/tokeninfo"
    timeout = httpx.Timeout(10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params={"id_token": id_token})
    except httpx.HTTPError as exc:
        raise OAuthValidationError("Could not validate Google token") from exc

    if response.status_code != 200:
        raise OAuthValidationError("Invalid Google token")

    payload = response.json()
    audience = str(payload.get("aud", "")).strip()
    if audience != settings.GOOGLE_OAUTH_CLIENT_ID:
        raise OAuthValidationError("Google token audience mismatch")

    issuer = str(payload.get("iss", "")).strip()
    valid_issuers = {"accounts.google.com", "https://accounts.google.com"}
    if issuer not in valid_issuers:
        raise OAuthValidationError("Google token issuer mismatch")

    exp_raw = str(payload.get("exp", "")).strip()
    try:
        exp_value = int(exp_raw)
    except ValueError as exc:
        raise OAuthValidationError("Google token expiration is invalid") from exc
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if exp_value <= now_ts:
        raise OAuthValidationError("Google token expired")

    email = str(payload.get("email", "")).strip().lower()
    sub = str(payload.get("sub", "")).strip()
    if not email or not sub:
        raise OAuthValidationError("Google token missing required claims")

    return {
        "provider": "google",
        "sub": sub,
        "email": email,
        "full_name": payload.get("name"),
        "picture": payload.get("picture"),
        "email_verified": str(payload.get("email_verified", "")).lower() == "true",
    }
