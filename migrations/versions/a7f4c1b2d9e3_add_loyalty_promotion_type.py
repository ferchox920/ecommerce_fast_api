"""add loyalty promotion type

Revision ID: a7f4c1b2d9e3
Revises: 2fc19ecd3738
Create Date: 2026-02-20 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a7f4c1b2d9e3"
down_revision: Union[str, Sequence[str], None] = "2fc19ecd3738"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE promotiontype ADD VALUE IF NOT EXISTS 'loyalty'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values in-place safely.
    pass
