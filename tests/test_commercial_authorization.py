import uuid

import pytest

from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
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
