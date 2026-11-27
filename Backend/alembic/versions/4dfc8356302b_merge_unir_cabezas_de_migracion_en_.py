"""merge: unir cabezas de migracion en develop

Revision ID: 4dfc8356302b
Revises: 9b4e6d1c2a7f, 9b4e6d2a8c15
Create Date: 2026-11-26 20:26:22.696614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dfc8356302b'
down_revision: Union[str, Sequence[str], None] = ('9b4e6d1c2a7f', '9b4e6d2a8c15')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
