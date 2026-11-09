"""Vacía el esquema `app` de dev para volver a migrar y sembrar (OPS-11).

Borra las tablas (incluida `alembic_version`) y los tipos enum del esquema `app` cuyo
dueño es el rol conectado, que en Neon es `svc_migrator`. No toca el esquema, los roles
ni los privilegios por defecto de `db/bootstrap_roles.sql`. Después hay que correr
`alembic upgrade head` y la semilla (`tools.seed_dev`); el workflow `dev-reset` lo hace.

No usa `alembic downgrade base` porque el `downgrade()` de la migración inicial no borra
los tipos enum y el `upgrade` siguiente fallaría al recrearlos.

Solo corre con APP_ENV=dev y `--confirmar dev`. Conecta con DATABASE_URL_MIGRATOR.

    APP_ENV=dev DATABASE_URL_MIGRATOR=... python -m tools.reset_dev --confirmar dev
"""

import argparse
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.db_url import preparar_conexion

ESQUEMA = "app"

_TABLAS_PROPIAS = text(
    """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :esquema AND c.relkind IN ('r', 'p')
      AND pg_get_userbyid(c.relowner) = current_user
    """
)

_TIPOS_PROPIOS = text(
    """
    SELECT t.typname
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = :esquema AND t.typtype = 'e'
      AND pg_get_userbyid(t.typowner) = current_user
    """
)


def _ident(nombre: str) -> str:
    return '"' + nombre.replace('"', '""') + '"'


async def vaciar_esquema(conn: AsyncConnection, esquema: str = ESQUEMA) -> tuple[int, int]:
    """Borra tablas y tipos enum propios del esquema. Devuelve (tablas, tipos)."""
    tablas = (await conn.execute(_TABLAS_PROPIAS, {"esquema": esquema})).scalars().all()
    if tablas:
        lista = ", ".join(f"{_ident(esquema)}.{_ident(t)}" for t in tablas)
        await conn.execute(text(f"DROP TABLE IF EXISTS {lista} CASCADE"))
    tipos = (await conn.execute(_TIPOS_PROPIOS, {"esquema": esquema})).scalars().all()
    if tipos:
        lista = ", ".join(f"{_ident(esquema)}.{_ident(t)}" for t in tipos)
        await conn.execute(text(f"DROP TYPE IF EXISTS {lista} CASCADE"))
    return len(tablas), len(tipos)


async def _ejecutar(url: str) -> tuple[int, int]:
    url_async, connect_args = preparar_conexion(url)
    motor = create_async_engine(url_async, poolclass=NullPool, connect_args=connect_args)
    try:
        async with motor.begin() as conn:  # una sola transacción: o se borra todo o nada
            return await vaciar_esquema(conn)
    finally:
        await motor.dispose()


def _info(mensaje: str) -> None:
    sys.stdout.write(f"{mensaje}\n")


def _error(mensaje: str) -> None:
    sys.stderr.write(f"ERROR: {mensaje}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vacía el esquema app de dev.")
    parser.add_argument("--confirmar", required=True, help='Escribe "dev" para confirmar.')
    args = parser.parse_args(argv)

    if os.environ.get("APP_ENV") != "dev" or args.confirmar != "dev":
        _error("el reset solo corre con APP_ENV=dev y --confirmar dev.")
        return 2
    url = os.environ.get("DATABASE_URL_MIGRATOR")
    if not url:
        _error("define DATABASE_URL_MIGRATOR en el entorno.")
        return 2

    tablas, tipos = asyncio.run(_ejecutar(url))
    _info(f"Esquema {ESQUEMA} vaciado: {tablas} tablas y {tipos} tipos borrados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
