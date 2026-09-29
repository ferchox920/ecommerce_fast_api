# tests/test_variants.py
import pytest
from httpx import AsyncClient


async def _crear_categoria_y_marca(client: AsyncClient, admin_token: str):
    r_cat = await client.post(
        "/api/v1/categories",
        json={"name": "Indumentaria"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_cat.status_code == 201, r_cat.text
    cat = r_cat.json()

    r_brand = await client.post(
        "/api/v1/brands",
        json={"name": "Zeta Wear"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_brand.status_code == 201, r_brand.text
    brand = r_brand.json()
    return cat, brand


async def _crear_producto_minimo(client: AsyncClient, admin_token: str):
    cat, brand = await _crear_categoria_y_marca(client, admin_token)
    payload = {
        "title": "Remera Tech",
        "price": 12999.00,
        "currency": "ARS",
        "category_id": cat["id"],
        "brand_id": brand["id"],
    }
    r = await client.post(
        "/api/v1/products",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_add_variant_ok(client: AsyncClient, admin_token: str):
    prod = await _crear_producto_minimo(client, admin_token)

    v_payload = {
        "sku": "REM-TECH-WHT-S",
        "barcode": "1234567890123",
        "size_label": "S",
        "color_name": "Blanco",
        "color_hex": "#FFFFFF",
        "stock_on_hand": 10,
        "stock_reserved": 2,
        "price_override": None,
        "active": True,
    }
    r = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=v_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sku"] == "REM-TECH-WHT-S"
    assert body["size_label"] == "S"
    assert body["color_name"] == "Blanco"
    assert body["stock_on_hand"] == 10
    assert body["stock_reserved"] == 2
    assert body["active"] is True


@pytest.mark.asyncio
async def test_add_variant_stock_invalido(client: AsyncClient, admin_token: str):
    prod = await _crear_producto_minimo(client, admin_token)

    # stock_reserved > stock_on_hand => 400
    bad_payload = {
        "sku": "REM-TECH-BLK-M",
        "size_label": "M",
        "color_name": "Negro",
        "color_hex": "#000000",
        "stock_on_hand": 0,
        "stock_reserved": 1,
        "active": True,
    }
    r = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=bad_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400
    assert "stock_reserved" in r.text.lower()


@pytest.mark.asyncio
async def test_add_variant_sku_duplicado(client: AsyncClient, admin_token: str):
    prod = await _crear_producto_minimo(client, admin_token)

    payload = {
        "sku": "REM-TECH-GRY-L",
        "size_label": "L",
        "color_name": "Gris",
        "color_hex": "#CCCCCC",
        "stock_on_hand": 5,
        "stock_reserved": 0,
        "active": True,
    }
    r1 = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r1.status_code == 201, r1.text

    # mismo SKU => debe fallar por unicidad (400)
    r2 = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 400
    assert "sku" in r2.text.lower() or "existe" in r2.text.lower()


@pytest.mark.asyncio
async def test_update_variant_stock_ok_y_luego_invalido(client: AsyncClient, admin_token: str):
    prod = await _crear_producto_minimo(client, admin_token)

    v_payload = {
        "sku": "REM-TECH-BLU-M",
        "size_label": "M",
        "color_name": "Azul",
        "color_hex": "#0000FF",
        "stock_on_hand": 3,
        "stock_reserved": 0,
        "active": True,
    }
    r_create = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=v_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_create.status_code == 201, r_create.text
    variant = r_create.json()

    # update válido
    r_ok = await client.put(
        f"/api/v1/products/variants/{variant['id']}",
        json={"stock_on_hand": 4},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_ok.status_code == 200, r_ok.text
    v2 = r_ok.json()
    assert v2["stock_on_hand"] == 4
    assert v2["stock_reserved"] == 0

    reserved = await client.post(
        f"/api/v1/products/variants/{variant['id']}/stock/reserve",
        json={"type": "reserve", "quantity": 1, "reason": "test reservation"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["stock_reserved"] == 1

    # update inválido: reservado > on_hand
    r_bad = await client.put(
        f"/api/v1/products/variants/{variant['id']}",
        json={"stock_on_hand": 1, "stock_reserved": 2},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_bad.status_code == 400
    assert "reserve" in r_bad.text.lower()


@pytest.mark.asyncio
async def test_delete_variant(client: AsyncClient, admin_token: str):
    prod = await _crear_producto_minimo(client, admin_token)

    v_payload = {
        "sku": "REM-TECH-RED-XL",
        "size_label": "XL",
        "color_name": "Rojo",
        "color_hex": "#FF0000",
        "stock_on_hand": 2,
        "stock_reserved": 0,
        "active": True,
    }
    r_create = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json=v_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_create.status_code == 201, r_create.text
    variant = r_create.json()

    r_del = await client.delete(
        f"/api/v1/products/variants/{variant['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_del.status_code == 204, r_del.text
