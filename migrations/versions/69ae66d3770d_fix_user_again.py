"""fix user again

Revision ID: 69ae66d3770d
Revises: f8853337fe7b
Create Date: 2025-10-21 17:52:35.585971

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '69ae66d3770d'
down_revision: Union[str, Sequence[str], None] = 'f8853337fe7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
