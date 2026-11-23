"""CLI de administración: ``create-admin`` y ``block-user`` (BE-20, RN-12).

Corre en cualquier entorno (dev o prod); en GitHub la ejecuta el workflow
``admin-cli`` (QA-18). Lee del entorno:
    DATABASE_URL       conexión a la base
    BLIND_INDEX_KEY    la misma clave que usa la API (índice ciego del correo)
    ADMIN_PASSWORD     solo para create-admin: contraseña del administrador
    ADMIN_CLI_EMAIL    opcional: el correo, si no se pasa con --email

La contraseña nunca se acepta por argumento ni se imprime. El correo tampoco se
imprime: la salida solo muestra ids. Así no queda nada personal en los logs.

    python -m tools.admin_cli create-admin --email admin@u.edu --nombre "Nombre Apellido"
    python -m tools.admin_cli block-user --email estudiante@u.edu

Códigos de salida: 0 bien, 1 error de los datos (cuenta inexistente, duplicada,
contraseña corta), 2 falta configuración.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

SALIDA_OK = 0
SALIDA_DATOS = 1
SALIDA_CONFIGURACION = 2


def _info(mensaje: str) -> None:
    sys.stdout.write(f"{mensaje}\n")


def _error(mensaje: str) -> None:
    sys.stderr.write(f"ERROR: {mensaje}\n")


async def _en_transaccion(operacion: Callable[..., Awaitable[Any]], **kwargs: Any) -> Any:
    """Corre una operación de ``app.services.usuarios`` y hace commit.

    Args:
        operacion: Función asíncrona que recibe la sesión como primer argumento.
        **kwargs: Argumentos de la operación.

    Returns:
        Lo que devuelva la operación.
    """
    # Importación local: app.config exige variables de entorno al importarse
    from app.database import SesionLocalAsync, motor_async

    try:
        async with SesionLocalAsync() as db:
            resultado = await operacion(db, **kwargs)
            await db.commit()
            return resultado
    finally:
        await motor_async.dispose()


def _crear_admin(args: argparse.Namespace, email: str) -> int:
    from app.services import usuarios

    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        _error("define ADMIN_PASSWORD en el entorno.")
        return SALIDA_CONFIGURACION
    admin = asyncio.run(
        _en_transaccion(usuarios.crear_admin, email=email, nombre=args.nombre, password=password)
    )
    _info(f"Administrador creado (id {admin.id}).")
    return SALIDA_OK


def _bloquear(email: str) -> int:
    from app.services import usuarios

    r = asyncio.run(_en_transaccion(usuarios.bloquear_usuario, email=email))
    estado = "ya estaba bloqueada" if r.ya_estaba_bloqueada else "bloqueada"
    acceso = f"acceso {r.sesion_cerrada} cerrado" if r.sesion_cerrada else "sin acceso activo"
    _info(
        f"Cuenta {r.user_id} {estado}: {r.refresh_revocados} sesiones web revocadas, {acceso}."
    )
    return SALIDA_OK


def construir_parser() -> argparse.ArgumentParser:
    """Arma el parser con los dos subcomandos.

    Returns:
        El parser listo para usar.
    """
    parser = argparse.ArgumentParser(description="Administración de cuentas (BE-20).")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("create-admin", help="Crea el administrador inicial.")
    crear.add_argument("--email", help="Correo (o ADMIN_CLI_EMAIL).")
    crear.add_argument("--nombre", required=True, help="Nombre completo.")
    bloquear = sub.add_parser(
        "block-user", help="Bloquea la cuenta, revoca sus sesiones web y cierra su acceso."
    )
    bloquear.add_argument("--email", help="Correo (o ADMIN_CLI_EMAIL).")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los del proceso.

    Returns:
        Código de salida del proceso.
    """
    args = construir_parser().parse_args(argv)
    email = args.email or os.environ.get("ADMIN_CLI_EMAIL")
    if not email:
        _error("indica el correo con --email o ADMIN_CLI_EMAIL.")
        return SALIDA_CONFIGURACION
    if not os.environ.get("BLIND_INDEX_KEY"):
        _error("define BLIND_INDEX_KEY (la misma de la API).")
        return SALIDA_CONFIGURACION

    try:
        if args.comando == "create-admin":
            return _crear_admin(args, email)
        return _bloquear(email)
    except ValueError as exc:  # incluye PasswordPolicyError y los errores de usuarios
        _error(str(exc))
        return SALIDA_DATOS


if __name__ == "__main__":
    raise SystemExit(main())
