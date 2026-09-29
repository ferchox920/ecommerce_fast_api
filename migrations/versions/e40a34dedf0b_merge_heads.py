"""merge heads

Revision ID: e40a34dedf0b
Revises: 2f6e7a8b9cde, 8f20b8a7c1b3
Create Date: 2025-10-21 17:02:18.363688
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'e40a34dedf0b'
down_revision: Union[str, Sequence[str], None] = ('2f6e7a8b9cde', '8f20b8a7c1b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    pass

def downgrade() -> None:
    """Downgrade schema."""
    pass
