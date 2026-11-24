"""Bloqueos transaccionales compartidos para operaciones sobre equipos."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _entero_con_signo(valor: int) -> int:
    """Convierte un entero de 32 bits sin signo a su representación con signo."""
    return valor if valor < 2**31 else valor - 2**32


async def bloquear_equipo(db: AsyncSession, machine_id: uuid.UUID) -> None:
    """Adquiere un bloqueo asesor transaccional exclusivo para un equipo.

    Args:
        db: Sesión activa de base de datos.
        machine_id: Identificador del equipo que se va a bloquear.

    El bloqueo se mantiene hasta que finalice la transacción mediante
    COMMIT o ROLLBACK.
    """
    identificador = machine_id.int
    clave_1 = _entero_con_signo((identificador >> 96) & 0xFFFFFFFF)
    clave_2 = _entero_con_signo((identificador >> 64) & 0xFFFFFFFF)

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:clave_1, :clave_2)"),
        {"clave_1": clave_1, "clave_2": clave_2},
    )
