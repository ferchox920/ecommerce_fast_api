import uuid

import pytest

from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
from app.models.cart import Cart, CartStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User


def _bearer(user_id, scopes):
    token = create_access_token(subject=user_id, extra={"scopes": scopes})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_customer_cannot_read_or_mutate_another_customers_order(
    client, db_session, normal_user, user_token
):
    other = User(
        email=f"other-{uuid.uuid4()}@example.com",
        is_active=True,
        is_superuser=False,
        email_verified=True,
    )
    db_session.add(other)
    db_session.flush()
    order = Order(user_id=str(other.id), status=OrderStatus.pending_payment)
    db_session.add(order)
    db_session.commit()

    headers = {"Authorization": f"Bearer {user_token}"}
    other_id = str(other.id)
    order_id = str(order.id)
    assert (await client.get("/api/v1/orders", headers=headers)).json() == []
    assert (await client.get(f"/api/v1/orders?user_id={other_id}", headers=headers)).status_code == 403
    assert (await client.get(f"/api/v1/orders/{order_id}", headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/orders/{order_id}/cancel", headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/orders/{order_id}/pay", headers=headers)).status_code == 403
    assert (await client.post(f"/api/v1/orders/{order_id}/lines", json={
        "variant_id": str(uuid.uuid4()), "quantity": 1
    }, headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/orders/{order_id}/fulfill", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_access_another_users_loyalty_or_admin_reports(
    client, user_token
):
    headers = {"Authorization": f"Bearer {user_token}"}
    other_id = str(uuid.uuid4())
    assert (await client.get(f"/api/v1/loyalty/profile?user_id={other_id}", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/loyalty/redeem", json={
        "user_id": other_id, "points": 1
    }, headers=headers)).status_code == 403
    assert (await client.get("/api/v1/reports/sales", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_stale_admin_scope_cannot_override_database_role(client, db_session):
    user = User(
        email=f"demoted-{uuid.uuid4()}@example.com",
        is_active=True,
        is_superuser=False,
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    response = await client.get(
        "/api/v1/admin/analytics/overview",
        headers=_bearer(user.id, ["admin"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_access_foreign_cart_payment_or_notification(
    client, db_session, user_token
):
    other = User(
        email=f"foreign-{uuid.uuid4()}@example.com",
        is_active=True,
        email_verified=True,
    )
    db_session.add(other)
    db_session.flush()
    cart = Cart(user_id=other.id, status=CartStatus.active, currency="ARS")
    order = Order(user_id=other.id, status=OrderStatus.pending_payment)
    notification = Notification(
        user_id=other.id,
        type=NotificationType.generic,
        title="Private",
        message="Private notification",
    )
    db_session.add_all([cart, order, notification])
    db_session.commit()

    headers = {"Authorization": f"Bearer {user_token}"}
    assert (await client.get("/api/v1/cart", headers=headers)).status_code == 404
    assert (
        await client.post(f"/api/v1/payments/orders/{order.id}", headers=headers)
    ).status_code == 403
    assert (await client.get("/api/v1/notifications", headers=headers)).json() == []
    assert (
        await client.patch(
            f"/api/v1/notifications/{notification.id}",
            json={"is_read": True},
            headers=headers,
        )
    ).status_code == 404


def test_notification_websocket_rejects_missing_and_invalid_tokens():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.main import app

    with TestClient(app) as client:
        for path in (
            "/api/v1/notifications/ws",
            "/api/v1/notifications/ws?token=invalid",
        ):
            with client.websocket_connect(path) as websocket:
                with pytest.raises(WebSocketDisconnect) as denied:
                    websocket.receive_text()
                assert denied.value.code == 4401
