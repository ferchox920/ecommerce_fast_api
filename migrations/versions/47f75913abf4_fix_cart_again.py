"""fix cart again

Revision ID: 47f75913abf4
Revises: 69ae66d3770d
Create Date: 2025-10-21 17:58:49.161667

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '47f75913abf4'
down_revision: Union[str, Sequence[str], None] = '69ae66d3770d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
