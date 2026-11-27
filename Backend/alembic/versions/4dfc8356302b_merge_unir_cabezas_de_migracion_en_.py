"""Une las cabezas de migracion de ST-SEC-01 y ST-SEC-03.

Revision ID: 4dfc8356302b
Revises: 9b4e6d1c2a7f, 9b4e6d2a8c15
Create Date: 2026-11-26 20:26:22.696614

"""

from collections.abc import Sequence

revision: str = "4dfc8356302b"
down_revision: str | Sequence[str] | None = ("9b4e6d1c2a7f", "9b4e6d2a8c15")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sin cambios de esquema."""


def downgrade() -> None:
    """Sin cambios de esquema."""
