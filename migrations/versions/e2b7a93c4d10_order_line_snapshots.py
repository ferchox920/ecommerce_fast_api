"""Preserve SKU and product title on order lines.

Revision ID: e2b7a93c4d10
Revises: d1a0c5e87b39
"""

from alembic import op
import sqlalchemy as sa

revision = "e2b7a93c4d10"
down_revision = "d1a0c5e87b39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_lines", sa.Column("sku_snapshot", sa.String(64), nullable=True))
    op.add_column("order_lines", sa.Column("product_title_snapshot", sa.String(200), nullable=True))
    op.execute(
        "UPDATE order_lines AS ol SET sku_snapshot = pv.sku, "
        "product_title_snapshot = p.title "
        "FROM product_variants AS pv JOIN products AS p ON p.id = pv.product_id "
        "WHERE ol.variant_id = pv.id"
    )


def downgrade() -> None:
    op.drop_column("order_lines", "product_title_snapshot")
    op.drop_column("order_lines", "sku_snapshot")
