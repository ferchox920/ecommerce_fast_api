"""fix cart 2

Revision ID: 2fc19ecd3738
Revises: 47f75913abf4
Create Date: 2025-10-21 18:02:36.921461

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '2fc19ecd3738'
down_revision: Union[str, Sequence[str], None] = '47f75913abf4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
