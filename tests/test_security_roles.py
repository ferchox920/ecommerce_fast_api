import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_user_cannot_create_category(client: AsyncClient, user_token: str):
    r = await client.post(
        "/api/v1/categories",
        json={"name": "SoloAdmin"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code in (401, 403)

@pytest.mark.asyncio
async def test_user_cannot_create_product(client: AsyncClient, user_token: str, admin_token: str):
    # Prepara base mínima con admin (cat + brand)
    rc = await client.post("/api/v1/categories", json={"name": "CatPrivada"},
                           headers={"Authorization": f"Bearer {admin_token}"})
    rb = await client.post("/api/v1/brands", json={"name": "BrandPrivada"},
                           headers={"Authorization": f"Bearer {admin_token}"})
    assert rc.status_code == 201 and rb.status_code == 201
    cat = rc.json()
    brand = rb.json()

    # Usuario normal intenta crear producto => prohibido
    r = await client.post(
        "/api/v1/products",
        json={
            "title": "Producto Prohibido",
            "price": 1000.0,
            "currency": "ARS",
            "category_id": cat["id"],
            "brand_id": brand["id"],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code in (401, 403)
