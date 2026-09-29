"""users.id to uuid + default

Revision ID: dac7cb15e79b
Revises: e40a34dedf0b
Create Date: 2025-10-21 17:40:10.663042

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'dac7cb15e79b'
down_revision: Union[str, Sequence[str], None] = 'e40a34dedf0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
