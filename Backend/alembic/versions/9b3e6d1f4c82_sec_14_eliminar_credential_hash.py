"""SEC-14: elimina credential_hash de machines.

El equipo se autentica solo con la firma RFC 9421, así que el hash de la
credencial provisional (SEC-05) ya no se usa. El borrado no se puede deshacer:
``downgrade`` recrea la columna vacía y los hashes anteriores no vuelven.

Revision ID: 9b3e6d1f4c82
Revises: 7c2d4f9a1b3e
Create Date: 2026-11-23 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b3e6d1f4c82"
down_revision: str | Sequence[str] | None = "7c2d4f9a1b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Borra la columna ``credential_hash`` y su restricción única."""
    op.drop_constraint("machines_credential_hash_key", "machines", schema="app", type_="unique")
    op.drop_column("machines", "credential_hash", schema="app")


def downgrade() -> None:
    """Recrea la columna vacía, con su restricción única."""
    op.add_column(
        "machines",
        sa.Column("credential_hash", sa.String(length=64), nullable=True),
        schema="app",
    )
    op.create_unique_constraint(
        "machines_credential_hash_key", "machines", ["credential_hash"], schema="app"
    )
