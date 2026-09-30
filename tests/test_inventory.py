import pytest
from httpx import AsyncClient
import uuid

async def _producto_minimo(client: AsyncClient, admin_token: str):
    cat_name = f"InvCat-{uuid.uuid4()}"
    brand_name = f"InvBrand-{uuid.uuid4()}"
    prod_title = f"InvProd-{uuid.uuid4()}"

    headers = {"Authorization": f"Bearer {admin_token}"}

    rc = await client.post("/api/v1/categories", json={"name": cat_name}, headers=headers)
    assert rc.status_code == 201, rc.text

    rb = await client.post("/api/v1/brands", json={"name": brand_name}, headers=headers)
    assert rb.status_code == 201, rb.text

    rp = await client.post(
        "/api/v1/products",
        json={
            "title": prod_title,
            "price": 1000.0,
            "currency": "ARS",
            "category_id": rc.json()["id"],
            "brand_id": rb.json()["id"],
        },
        headers=headers,
    )
    assert rp.status_code == 201, rp.text
    return rp.json()


@pytest.mark.asyncio
async def test_receive_reserve_release_sale_flow(client: AsyncClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    prod = await _producto_minimo(client, admin_token)

    # crear variante con SKU único
    sku1 = f"INV-001-{uuid.uuid4()}"
    rv = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json={
            "sku": sku1,
            "size_label": "U",
            "color_name": "Negro",
            "color_hex": "#000000",
            "stock_on_hand": 0,
            "stock_reserved": 0,
            "active": True
        },
        headers=headers
    )
    assert rv.status_code == 201, rv.text
    var = rv.json()

    # receive 10
    r1 = await client.post(
        f"/api/v1/products/variants/{var['id']}/stock/receive",
        json={"type": "receive", "quantity": 10, "reason": "test: initial receive"},
        headers=headers
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["stock_on_hand"] == 10 and body1["stock_reserved"] == 0

    # reserve 6
    r2 = await client.post(
        f"/api/v1/products/variants/{var['id']}/stock/reserve",
        json={"type": "reserve", "quantity": 6, "reason": "test: reserve"},
        headers=headers
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["stock_reserved"] == 6 and body2["stock_on_hand"] == 10

    # release 2
    r3 = await client.post(
        f"/api/v1/products/variants/{var['id']}/stock/release",
        json={"type": "release", "quantity": 2, "reason": "test: release"},
        headers=headers
    )
    assert r3.status_code == 200, r3.text
    v3 = r3.json()
    assert v3["stock_reserved"] == 4 and v3["stock_on_hand"] == 10

    # La venta directa consume stock libre y conserva las reservas.
    r4 = await client.post(
        f"/api/v1/products/variants/{var['id']}/stock/sale",
        json={"type": "sale", "quantity": 3, "reason": "test: sale"},
        headers=headers
    )
    assert r4.status_code == 200, r4.text
    v4 = r4.json()
    assert v4["stock_reserved"] == 4 and v4["stock_on_hand"] == 7

    # movimientos: validar tipos y que haya al menos los 4
    rm = await client.get(
        f"/api/v1/products/variants/{var['id']}/stock/movements",
        headers=headers
    )
    assert rm.status_code == 200, rm.text
    moves = rm.json()
    assert len(moves) >= 4

    types = [m["type"] for m in moves]
    for expected in ["receive", "reserve", "release", "sale"]:
        assert expected in types


@pytest.mark.asyncio
async def test_reserve_more_than_available_fails(client: AsyncClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    prod = await _producto_minimo(client, admin_token)

    # variante con SKU único para evitar colisiones
    sku2 = f"INV-002-{uuid.uuid4()}"
    rv = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json={
            "sku": sku2,
            "size_label": "U",
            "color_name": "Azul",
            "color_hex": "#0000FF",
            "stock_on_hand": 5,
            "stock_reserved": 0,
            "active": True
        },
        headers=headers
    )
    assert rv.status_code == 201, rv.text
    var = rv.json()

    r = await client.post(
        f"/api/v1/products/variants/{var['id']}/stock/reserve",
        json={"type": "reserve", "quantity": 6, "reason": "test: over-reserve"},
        headers=headers
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_receive_retry_key_does_not_duplicate_stock_or_audit(
    client: AsyncClient, admin_token: str
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    product = await _producto_minimo(client, admin_token)
    variant = await client.post(
        f"/api/v1/products/{product['id']}/variants",
        json={
            "sku": f"IDEM-{uuid.uuid4()}", "size_label": "M", "color_name": "Black",
            "stock_on_hand": 0,
        },
        headers=headers,
    )
    assert variant.status_code == 201, variant.text
    variant_id = variant.json()["id"]
    request = {
        "type": "receive", "quantity": 2, "reason": "retry-test",
        "idempotency_key": f"receive-{uuid.uuid4()}",
    }
    url = f"/api/v1/products/variants/{variant_id}/stock/receive"
    first = await client.post(url, json=request, headers=headers)
    second = await client.post(url, json=request, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json()["stock_on_hand"] == 2
    changed = await client.post(url, json={**request, "quantity": 3}, headers=headers)
    assert changed.status_code == 400
    movements = await client.get(
        f"/api/v1/products/variants/{variant_id}/stock/movements", headers=headers
    )
    assert movements.status_code == 200
    assert len(movements.json()) == 1
