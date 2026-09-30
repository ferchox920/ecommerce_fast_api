"""Restore inventory schema and add commercial idempotency guards.

Revision ID: d1a0c5e87b39
Revises: c4d5e6f7a8b9
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1a0c5e87b39"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("applied_promotion_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_orders_applied_promotion_id", "orders", "promotions",
        ["applied_promotion_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("orders", sa.Column("idempotency_key", sa.String(120), nullable=True))
    op.add_column("orders", sa.Column("request_fingerprint", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_orders_user_idempotency_key", "orders", ["user_id", "idempotency_key"]
    )
    op.add_column("orders", sa.Column("source_cart_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_orders_source_cart_id", "orders", "carts", ["source_cart_id"], ["id"], ondelete="SET NULL"
    )
    op.create_unique_constraint("uq_orders_source_cart_id", "orders", ["source_cart_id"])
    op.add_column("payment_webhook_events", sa.Column("event_type", sa.String(80), nullable=True))
    op.add_column("payment_webhook_events", sa.Column("outcome", sa.String(40), nullable=True))
    op.add_column("payment_refunds", sa.Column("idempotency_key", sa.String(120), nullable=True))
    op.create_unique_constraint(
        "uq_payment_refund_idempotency", "payment_refunds", ["payment_id", "idempotency_key"]
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "type",
            sa.Enum("RECEIVE", "ADJUST", "RESERVE", "RELEASE", "SALE", name="inventory_movement_type"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("variant_id", "idempotency_key", name="uq_inventory_movement_idempotency"),
    )
    op.create_index("ix_inventory_movements_variant_id", "inventory_movements", ["variant_id"])
    op.create_index(
        "ix_inventory_movements_variant_created",
        "inventory_movements",
        ["variant_id", "created_at"],
    )
    op.add_column(
        "product_variants",
        sa.Column("primary_supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_product_variants_primary_supplier_id",
        "product_variants",
        "suppliers",
        ["primary_supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_product_variants_on_hand_nonnegative", "product_variants", "stock_on_hand >= 0"
    )
    op.create_check_constraint(
        "ck_product_variants_reserved_within_on_hand",
        "product_variants",
        "stock_reserved >= 0 AND stock_reserved <= stock_on_hand",
    )


def downgrade() -> None:
    op.drop_constraint("fk_orders_applied_promotion_id", "orders")
    op.drop_column("orders", "applied_promotion_id")
    op.drop_constraint("uq_orders_user_idempotency_key", "orders")
    op.drop_column("orders", "request_fingerprint")
    op.drop_column("orders", "idempotency_key")
    op.drop_constraint("uq_orders_source_cart_id", "orders")
    op.drop_constraint("fk_orders_source_cart_id", "orders")
    op.drop_column("orders", "source_cart_id")
    op.drop_column("payment_webhook_events", "outcome")
    op.drop_column("payment_webhook_events", "event_type")
    op.drop_constraint("uq_payment_refund_idempotency", "payment_refunds")
    op.drop_column("payment_refunds", "idempotency_key")
    op.drop_constraint("ck_product_variants_reserved_within_on_hand", "product_variants")
    op.drop_constraint("ck_product_variants_on_hand_nonnegative", "product_variants")
    op.drop_constraint("fk_product_variants_primary_supplier_id", "product_variants")
    op.drop_column("product_variants", "primary_supplier_id")
    op.drop_index("ix_inventory_movements_variant_created", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_variant_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    sa.Enum(name="inventory_movement_type").drop(op.get_bind(), checkfirst=True)
