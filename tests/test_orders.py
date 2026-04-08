import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timezone


async def _create_base(client: AsyncClient, admin_token: str):
    r_cat = await client.post(
        "/api/v1/categories",
        json={"name": f"OrdersCat-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_cat.status_code == 201, r_cat.text
    cat = r_cat.json()

    r_brand = await client.post(
        "/api/v1/brands",
        json={"name": f"OrdersBrand-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_brand.status_code == 201, r_brand.text
    brand = r_brand.json()

    r_prod = await client.post(
        "/api/v1/products",
        json={
            "title": "Producto Orders",
            "price": 1500.0,
            "currency": "ARS",
            "category_id": cat["id"],
            "brand_id": brand["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_prod.status_code == 201, r_prod.text
    prod = r_prod.json()

    rv = await client.post(
        f"/api/v1/products/{prod['id']}/variants",
        json={
            "sku": f"SO-TEST-{uuid.uuid4()}",
            "size_label": "U",
            "color_name": "Azul",
            "stock_on_hand": 10,
            "active": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rv.status_code == 201, rv.text
    variant = rv.json()
    return prod, variant


@pytest.mark.asyncio
async def test_order_create_and_get(client: AsyncClient, admin_token: str, user_token: str):
    _, variant = await _create_base(client, admin_token)

    ro = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ARS",
            "lines": [
                {"variant_id": variant["id"], "quantity": 2}
            ],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ro.status_code == 201, ro.text
    order = ro.json()
    assert order["status"] == "pending_payment"
    assert order["payment_status"] == "pending"
    assert len(order["lines"]) == 1
    assert order["lines"][0]["quantity"] == 2
    assert order["total_amount"] == 3000.0

    rg = await client.get(
        f"/api/v1/orders/{order['id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert rg.status_code == 200
    og = rg.json()
    assert og["id"] == order["id"]
    assert og["payment_status"] == "pending"
    assert og["shipping_status"] == "pending"


@pytest.mark.asyncio
async def test_order_add_line_pay_and_fulfill(client: AsyncClient, admin_token: str, user_token: str):
    _, variant = await _create_base(client, admin_token)

    ro = await client.post(
        "/api/v1/orders",
        json={
            "lines": [
                {"variant_id": variant["id"], "quantity": 1}
            ],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ro.status_code == 201
    order = ro.json()

    add = await client.post(
        f"/api/v1/orders/{order['id']}/lines",
        json={
            "variant_id": variant["id"],
            "quantity": 3,
            "unit_price": 2000.0,
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert add.status_code == 200, add.text
    updated = add.json()
    assert len(updated["lines"]) == 2
    assert updated["total_amount"] == 7500.0

    pay = await client.post(
        f"/api/v1/orders/{order['id']}/pay",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert pay.status_code == 200, pay.text
    paid = pay.json()
    assert paid["status"] == "paid"
    assert paid["payment_status"] == "approved"
    assert paid["shipping_status"] == "pending"
    assert paid["shipments"] == []

    fulfill_payload = {
        "carrier": "FastShip",
        "tracking_number": "TRACK-123",
        "shipped_at": datetime.now(timezone.utc).isoformat(),
    }
    fulfill = await client.post(
        f"/api/v1/orders/{order['id']}/fulfill",
        json=fulfill_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fulfill.status_code == 200, fulfill.text
    fulfilled = fulfill.json()
    assert fulfilled["status"] == "fulfilled"
    assert fulfilled["shipping_status"] == "shipped"
    assert len(fulfilled["shipments"]) == 1
    shipment = fulfilled["shipments"][0]
    assert shipment["carrier"] == "FastShip"
    assert shipment["tracking_number"] == "TRACK-123"


@pytest.mark.asyncio
async def test_admin_cannot_create_customer_order(client: AsyncClient, admin_token: str):
    _, variant = await _create_base(client, admin_token)

    ro = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ARS",
            "lines": [
                {"variant_id": variant["id"], "quantity": 1}
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ro.status_code == 403, ro.text
    assert ro.json()["detail"] == "Admin users cannot create customer orders"


@pytest.mark.asyncio
async def test_order_from_cart_flow(client: AsyncClient, admin_token: str):
    _, variant = await _create_base(client, admin_token)
    guest_token = f"guest-{uuid.uuid4()}"

    create_cart = await client.post(
        "/api/v1/cart",
        json={"guest_token": guest_token, "currency": "ARS"},
    )
    assert create_cart.status_code == 201

    add_item = await client.post(
        "/api/v1/cart/items",
        params={"guest_token": guest_token},
        json={"variant_id": variant["id"], "quantity": 2},
    )
    assert add_item.status_code == 201, add_item.text

    order_resp = await client.post(
        "/api/v1/orders/from-cart",
        json={"guest_token": guest_token},
    )
    assert order_resp.status_code == 201, order_resp.text
    order = order_resp.json()
    assert order["status"] == "pending_payment"
    assert order["payment_status"] == "pending"
    assert len(order["lines"]) == 1
    assert order["lines"][0]["quantity"] == 2

    cart_after = await client.get(
        "/api/v1/cart",
        params={"guest_token": guest_token},
    )
    assert cart_after.status_code == 404
