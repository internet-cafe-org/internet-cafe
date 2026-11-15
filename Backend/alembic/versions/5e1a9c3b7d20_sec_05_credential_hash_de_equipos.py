"""SEC-05: columna credential_hash en machines.

Hasta ahora ``require_machine`` guardaba el SHA-256 de la credencial provisional
en ``key_thumbprint``, que el SRS (§11.2 y §12.4) reserva para la huella RFC 7638
de la clave pública. Esta migración separa los dos datos:

- agrega ``credential_hash`` (SHA-256 en hex, único);
- mueve a ella los valores de ``key_thumbprint`` de los equipos sin JWK, que son
  hashes de credencial y no huellas; así los equipos de dev conservan su
  credencial.

Revision ID: 5e1a9c3b7d20
Revises: 8548f2b62d28
Create Date: 2026-11-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e1a9c3b7d20"
down_revision: str | Sequence[str] | None = "8548f2b62d28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Agrega ``credential_hash`` y mueve a ella los hashes de credencial."""
    op.add_column(
        "machines",
        sa.Column("credential_hash", sa.String(length=64), nullable=True),
        schema="app",
    )
    op.create_unique_constraint(
        "machines_credential_hash_key", "machines", ["credential_hash"], schema="app"
    )
    op.execute(
        "UPDATE app.machines "
        "SET credential_hash = key_thumbprint, key_thumbprint = NULL "
        "WHERE public_key_jwk IS NULL AND key_thumbprint IS NOT NULL"
    )


def downgrade() -> None:
    """Devuelve los hashes de credencial a ``key_thumbprint`` y borra la columna."""
    op.execute(
        "UPDATE app.machines "
        "SET key_thumbprint = credential_hash "
        "WHERE public_key_jwk IS NULL AND credential_hash IS NOT NULL"
    )
    op.drop_constraint("machines_credential_hash_key", "machines", schema="app", type_="unique")
    op.drop_column("machines", "credential_hash", schema="app")
