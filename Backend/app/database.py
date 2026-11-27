"""Módulo de configuración de la Base de Datos Asíncrona.

Establece la conexión con el motor de base de datos de forma asíncrona
utilizando SQLAlchemy y SQLAlchemy Asyncio.

ST-SEC-03 (SRS §12.8): cada actor de la API usa su propio rol de PostgreSQL.

| Actor    | Variable               | Rol          | Rutas                         |
|----------|------------------------|--------------|-------------------------------|
| web      | ``DATABASE_URL_WEB``     | svc_web      | ``/auth``, ``/me``, ``/scan`` y salud |
| maquina  | ``DATABASE_URL_MACHINE`` | svc_machine  | ``/machine/*``                |
| admin    | ``DATABASE_URL_ADMIN``   | svc_admin    | ``/admin/*``                  |
| tareas   | ``DATABASE_URL_JOBS``    | svc_jobs     | Barrido de inactividad        |

Si la variable de un actor no está definida, ese actor usa ``DATABASE_URL``
(transición: local, CI y los entornos que todavía tienen un solo rol). Los
actores con la misma URL comparten un único motor, así que no se abren más
conexiones de las que había.
"""

from collections.abc import AsyncIterator
from typing import Literal

from app.config import settings
from app.db_url import preparar_conexion
from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, declarative_base

Actor = Literal["web", "maquina", "admin", "tareas"]

# Prefijos de ruta de cada actor. Todo lo demás (/auth, /me, /scan, /healthz,
# /readyz) es del actor web.
_PREFIJOS: tuple[tuple[str, Actor], ...] = (
    ("/api/v1/machine/", "maquina"),
    ("/api/v1/admin/", "admin"),
)


def _crear_motor(url: str, pool_size: int) -> AsyncEngine:
    """Crea un motor asíncrono para la URL dada.

    - echo=False: con echo=True SQLAlchemy escribe en el log cada sentencia con sus
      parámetros, y ahí viajan correos, códigos y hashes (SRS §12.7: registros sin PII).
    - pool_pre_ping: Neon suspende el cómputo tras 5 min sin uso y las conexiones del
      pool quedan muertas; el ping las detecta antes de entregarlas.

    Args:
        url: URL de PostgreSQL (se acepta la de Neon tal cual).
        pool_size: Tamaño del pool de conexiones.

    Returns:
        Motor asíncrono listo para usar.
    """
    url_limpia, connect_args = preparar_conexion(url)
    return create_async_engine(
        url_limpia,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=pool_size,
        pool_recycle=settings.db_pool_recycle_s,
        connect_args=connect_args,
    )


# Motor por defecto (DATABASE_URL). Lo usan los actores sin URL propia y las
# herramientas de línea de comandos (tools/).
motor_async = _crear_motor(settings.database_url, settings.db_pool_size)

_motores_por_url: dict[str, AsyncEngine] = {settings.database_url: motor_async}


def _motor_de(url: str | None, pool_size: int) -> AsyncEngine:
    """Devuelve el motor de una URL; si no hay URL propia, el motor por defecto.

    Args:
        url: URL del actor o ``None`` si no se configuró.
        pool_size: Tamaño del pool si hay que crear el motor.

    Returns:
        El motor (compartido si otra variable tiene la misma URL).
    """
    if not url:
        return motor_async
    if url not in _motores_por_url:
        _motores_por_url[url] = _crear_motor(url, pool_size)
    return _motores_por_url[url]


# Pools de 5, 5, 2 y 2 conexiones (SRS §12.8)
motores: dict[Actor, AsyncEngine] = {
    "web": _motor_de(settings.database_url_web, 5),
    "maquina": _motor_de(settings.database_url_machine, 5),
    "admin": _motor_de(settings.database_url_admin, 2),
    "tareas": _motor_de(settings.database_url_jobs, 2),
}

fabricas: dict[Actor, async_sessionmaker[AsyncSession]] = {
    actor: async_sessionmaker(motor, class_=AsyncSession, expire_on_commit=False)
    for actor, motor in motores.items()
}

SesionWeb = fabricas["web"]
SesionMaquina = fabricas["maquina"]
SesionAdmin = fabricas["admin"]
SesionTareas = fabricas["tareas"]

# Fábrica del motor por defecto: la usan las herramientas de tools/.
SesionLocalAsync = async_sessionmaker(motor_async, class_=AsyncSession, expire_on_commit=False)

# Base declarativa de la cual heredarán todos los modelos ORM del sistema (como UsuarioModelo y RolModelo)
Base = declarative_base()


def actor_de_ruta(ruta: str) -> Actor:
    """Devuelve el actor que atiende una ruta HTTP.

    Args:
        ruta: Ruta de la petición (``request.url.path``).

    Returns:
        ``"maquina"`` para ``/api/v1/machine/*``, ``"admin"`` para
        ``/api/v1/admin/*`` y ``"web"`` para el resto.
    """
    for prefijo, actor in _PREFIJOS:
        if ruta.startswith(prefijo):
            return actor
    return "web"


async def obtener_base_datos(request: Request) -> AsyncIterator[AsyncSession]:
    """Genera una sesión de base de datos asíncrona por cada solicitud HTTP.

    La sesión sale del motor del actor que atiende la ruta (ST-SEC-03), así cada
    router opera solo con los privilegios de su rol.

    Args:
        request: Petición HTTP en curso (la inyecta FastAPI).

    Yields:
        AsyncSession: Sesión activa de base de datos para realizar operaciones.
    """
    # Abre una sesión asíncrona asegurando su cierre automático al finalizar la petición
    async with fabricas[actor_de_ruta(request.url.path)]() as sesion:
        yield sesion



# --------------------------------------------------------------------- RLS (ST-SEC-05)
# Variables de sesión que leen las políticas RLS (SRS §12.8). Son locales a la
# transacción (``set_config(..., true)``), así que se guardan en ``sesion.info`` y
# se vuelven a fijar al empezar cada transacción: una petición puede hacer varios
# commit y la variable no debe perderse entre ellos.
VARIABLES_RLS = frozenset(
    {
        "user_id",  # usuario autenticado (svc_web)
        "machine_id",  # equipo autenticado (svc_machine)
        "machine_user_id",  # estudiante con sesión abierta en ese equipo
        "refresh_hash",  # hash del refresh token presentado (renovar / cerrar sesión)
        "challenge_hash",  # hash del token del QR escaneado
        "claim_machine_id",  # equipo del QR escaneado (ver si está ocupado)
    }
)
_CLAVE_INFO = "rls"


async def fijar_contexto_rls(sesion: AsyncSession, **valores: object) -> None:
    """Fija variables ``app.*`` para las políticas RLS en esta sesión.

    Args:
        sesion: Sesión de base de datos de la petición.
        **valores: Variables de ``VARIABLES_RLS``. Los UUID se pasan tal cual y
            los hashes como ``bytes`` (se guardan en hexadecimal).

    Raises:
        ValueError: Si se pasa una variable que no está en ``VARIABLES_RLS``.
    """
    if not isinstance(sesion, AsyncSession):
        # Pruebas unitarias con una sesión simulada: no hay base de datos que filtrar.
        return
    contexto: dict[str, str] = sesion.info.setdefault(_CLAVE_INFO, {})
    for nombre, valor in valores.items():
        if nombre not in VARIABLES_RLS:
            raise ValueError(f"variable RLS desconocida: {nombre}")
        contexto[nombre] = valor.hex() if isinstance(valor, bytes) else str(valor)
    for nombre in valores:
        await sesion.execute(
            text("SELECT set_config(:nombre, :valor, true)"),
            {"nombre": f"app.{nombre}", "valor": contexto[nombre]},
        )


@event.listens_for(Session, "after_begin")
def _reaplicar_contexto_rls(sesion: Session, _transaccion, conexion) -> None:
    """Vuelve a fijar las variables RLS al empezar cada transacción."""
    for nombre, valor in sesion.info.get(_CLAVE_INFO, {}).items():
        conexion.execute(
            text("SELECT set_config(:nombre, :valor, true)"),
            {"nombre": f"app.{nombre}", "valor": valor},
        )
