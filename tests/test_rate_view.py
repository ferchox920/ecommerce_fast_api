import uuid
import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone


def _utc_iso(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


async def _create_product_with_variant(client: AsyncClient, admin_token: str):
    cat_resp = await client.post(
        "/api/v1/categories",
        json={"name": f"RV-Cat-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    cat = cat_resp.json()
    brand_resp = await client.post(
        "/api/v1/brands",
        json={"name": f"RV-Brand-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    brand = brand_resp.json()
    prod_resp = await client.post(
        "/api/v1/products",
        json={
            "title": "Rate View Producto",
            "price": 100.0,
            "currency": "ARS",
            "category_id": cat["id"],
            "brand_id": brand["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    product = prod_resp.json()
    variant_resp = await client.post(
        f"/api/v1/products/{product['id']}/variants",
        json={
            "sku": f"RV-{uuid.uuid4()}",
            "size_label": "U",
            "color_name": "Azul",
            "stock_on_hand": 10,
            "active": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    variant = variant_resp.json()
    return product, variant


@pytest.mark.asyncio
async def test_rate_view_pipeline(client: AsyncClient, admin_token: str, user_token: str):
    product, variant = await _create_product_with_variant(client, admin_token)

    user_resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert user_resp.status_code == 200
    user = user_resp.json()
    user_id = user["id"]

    # enviar eventos de view/click/purchase
    for _ in range(3):
        resp = await client.post(
            "/api/v1/events",
            json={
                "event_type": "view",
                "product_id": product["id"],
                "user_id": user_id,
                "timestamp": _utc_iso(),
            },
        )
        assert resp.status_code == 202

    purchase_resp = await client.post(
        "/api/v1/events",
        json={
            "event_type": "purchase",
            "product_id": product["id"],
            "user_id": user_id,
            "timestamp": _utc_iso(),
            "price": 120.5,
            "metadata": {"quantity": 1},
        },
    )
    assert purchase_resp.status_code == 202

    # run scoring
    scoring_resp = await client.post(
        "/api/v1/internal/scoring/run",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert scoring_resp.status_code == 200
    assert scoring_resp.json()["count"] >= 1

    exposure_resp = await client.get(
        "/api/v1/exposure",
        params={"context": "home", "limit": 5},
    )
    assert exposure_resp.status_code == 200
    exposure_data = exposure_resp.json()
    assert exposure_data["mix"], exposure_data

    # create and activate promotion
    promo_resp = await client.post(
        "/api/v1/admin/promotions",
        json={
            "name": "Promo Test",
            "description": "Test promo",
            "type": "product",
            "criteria": {"product_ids": [product["id"]]},
            "benefits": {"discount_percent": 10},
            "start_at": _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=1)),
            "end_at": _utc_iso(datetime.now(timezone.utc) + timedelta(days=5)),
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert promo_resp.status_code == 201
    promo_id = promo_resp.json()["id"]

    activate_resp = await client.post(
        f"/api/v1/admin/promotions/{promo_id}/activate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert activate_resp.status_code == 200

    # loyalty profile should exist for user
    loyalty_resp = await client.get(
        "/api/v1/loyalty/profile",
        params={"user_id": user_id},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert loyalty_resp.status_code == 200
    loyalty_data = loyalty_resp.json()
    assert loyalty_data["points"] >= 10

    analytics_resp = await client.get(
        "/api/v1/admin/analytics/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert analytics_resp.status_code == 200
    analytics = analytics_resp.json()
    assert "kpis" in analytics

    dashboard_resp = await client.get(
        "/api/v1/admin/analytics/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert "sales" in dashboard
    assert "inventory" in dashboard
    assert "operations" in dashboard

