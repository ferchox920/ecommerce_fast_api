"""payment hardening

Revision ID: b7c3d9e4f1a2
Revises: 2f6e7a8b9cde
Create Date: 2026-04-07 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b7c3d9e4f1a2"
down_revision: Union[str, Sequence[str], None] = "a7f4c1b2d9e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    provider_enum = postgresql.ENUM(
        "mercado_pago",
        name="paymentprovider",
        create_type=False,
    )
    provider_enum.create(bind, checkfirst=True)

    op.add_column("orders", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("payments", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
    op.add_column("payments", sa.Column("raw_refund", sa.JSON(), nullable=True))
    op.add_column("payments", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("refund_reason", sa.String(length=240), nullable=True))
    op.add_column("payments", sa.Column("provider_refund_id", sa.String(length=140), nullable=True))
    op.create_unique_constraint(
        "uq_payments_order_idempotency_key",
        "payments",
        ["order_id", "idempotency_key"],
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", provider_enum, nullable=False),
        sa.Column("event_id", sa.String(length=140), nullable=False),
        sa.Column("request_id", sa.String(length=140), nullable=True),
        sa.Column("signature", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_payment_webhook_provider_event",
        "payment_webhook_events",
        ["provider", "event_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payment_webhook_provider_event", "payment_webhook_events", type_="unique")
    op.drop_table("payment_webhook_events")

    op.drop_constraint("uq_payments_order_idempotency_key", "payments", type_="unique")
    op.drop_column("payments", "provider_refund_id")
    op.drop_column("payments", "refund_reason")
    op.drop_column("payments", "refunded_at")
    op.drop_column("payments", "raw_refund")
    op.drop_column("payments", "idempotency_key")

    op.drop_column("orders", "refunded_at")
