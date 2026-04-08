"""payment refund audit

Revision ID: c4d5e6f7a8b9
Revises: b7c3d9e4f1a2
Create Date: 2026-04-07 13:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b7c3d9e4f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE paymentstatus ADD VALUE IF NOT EXISTS 'partially_refunded'")

    op.add_column("payments", sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("payment_webhook_events", sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_payment_webhook_events_payment_id",
        "payment_webhook_events",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "payment_refunds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(length=240), nullable=True),
        sa.Column("provider_refund_id", sa.String(length=140), nullable=True),
        sa.Column("status_detail", sa.String(length=120), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"], unique=False)

    op.alter_column("payments", "refunded_amount", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_payment_refunds_payment_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")

    op.drop_constraint("fk_payment_webhook_events_payment_id", "payment_webhook_events", type_="foreignkey")
    op.drop_column("payment_webhook_events", "payment_id")
    op.drop_column("payments", "refunded_amount")

    # PostgreSQL does not support removing enum values safely in-place.
    pass
