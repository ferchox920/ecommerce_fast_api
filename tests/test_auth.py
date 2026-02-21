# tests/test_auth.py
import pytest
from app.services.oauth_service import OAuthValidationError

LOGIN_URL = "/api/v1/auth/login"
PROTECTED_URL = "/api/v1/categories"
OAUTH_EXCHANGE_URL = "/api/v1/auth/oauth/exchange"
OAUTH_CONFIG_URL = "/api/v1/auth/oauth/config"
FAKE_LONG_TOKEN = "fake-id-token-abcdefghijklmnopqrstuvwxyz-123456"

@pytest.mark.asyncio
async def test_login_success(client, admin_user):
    resp = await client.post(
        LOGIN_URL,
        data={"username": admin_user.email, "password": "Admin1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # tokens típicos
    assert "access_token" in body
    assert body.get("token_type", "").lower() in ("bearer", "jwt", "access")

@pytest.mark.asyncio
async def test_login_wrong_password(client, admin_user):
    resp = await client.post(
        LOGIN_URL,
        data={"username": admin_user.email, "password": "wrong-pass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # algunos auth devuelven 400, otros 401 -> aceptamos ambos
    assert resp.status_code in (400, 401), resp.text
    msg = resp.text.lower()
    assert ("invalid" in msg) or ("incorrect" in msg) or ("unauthorized" in msg)

@pytest.mark.asyncio
async def test_protected_requires_auth(client):
    # crear categoría sin token => 401
    resp = await client.post(PROTECTED_URL, json={"name": "Protegida"})
    assert resp.status_code in (401, 403), resp.text

@pytest.mark.asyncio
async def test_protected_with_token(client, admin_token):
    # crear categoría con token => 201
    resp = await client.post(
        PROTECTED_URL,
        json={"name": "Autorizada"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Autorizada"
    assert "slug" in data
    assert data.get("active") is True


@pytest.mark.asyncio
async def test_oauth_exchange_success(client, monkeypatch):
    async def _fake_verify(provider: str, id_token: str):
        assert provider == "google"
        assert id_token == FAKE_LONG_TOKEN
        return {
            "provider": "google",
            "sub": "google-user-123",
            "email": "oauth.user@example.com",
            "full_name": "OAuth User",
            "picture": "https://example.com/pic.jpg",
            "email_verified": True,
        }

    monkeypatch.setattr("app.api.routers.auth.verify_provider_id_token", _fake_verify)

    resp = await client.post(
        OAUTH_EXCHANGE_URL,
        json={"provider": "google", "id_token": FAKE_LONG_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["email"] == "oauth.user@example.com"
    assert body["user"]["oauth_provider"] == "google"


@pytest.mark.asyncio
async def test_oauth_exchange_invalid_token(client, monkeypatch):
    async def _fake_verify(provider: str, id_token: str):
        raise OAuthValidationError("Invalid Google token")

    monkeypatch.setattr("app.api.routers.auth.verify_provider_id_token", _fake_verify)

    resp = await client.post(
        OAUTH_EXCHANGE_URL,
        json={"provider": "google", "id_token": FAKE_LONG_TOKEN},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Invalid Google token"


@pytest.mark.asyncio
async def test_oauth_config_lists_google_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.oauth_service.settings.GOOGLE_OAUTH_CLIENT_ID",
        "google-client-id.apps.googleusercontent.com",
    )
    resp = await client.get(OAUTH_CONFIG_URL)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["providers"]
    assert data["providers"][0]["provider"] == "google"
