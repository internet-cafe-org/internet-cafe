"""Módulo de configuración de la Base de Datos Asíncrona.

Establece la conexión con el motor de base de datos de forma asíncrona
utilizando SQLAlchemy y SQLAlchemy Asyncio.
"""

from app.config import settings
from app.db_url import preparar_conexion
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# La URL puede venir de Neon (con sslmode / channel_binding): se normaliza para asyncpg.
_url, _connect_args = preparar_conexion(settings.database_url)

# Motor asíncrono del rol de la API (svc_app).
# - echo=False: con echo=True SQLAlchemy escribe en el log cada sentencia con sus
#   parámetros, y ahí viajan correos, códigos y hashes (SRS §12.7: registros sin PII).
# - pool_pre_ping: Neon suspende el cómputo tras 5 min sin uso y las conexiones del
#   pool quedan muertas; el ping las detecta antes de entregarlas.
motor_async = create_async_engine(
    _url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    pool_recycle=settings.db_pool_recycle_s,
    connect_args=_connect_args,
)

# Fábrica de sesiones asíncronas para interactuar con la base de datos por cada petición HTTP
SesionLocalAsync = async_sessionmaker(
    motor_async, class_=AsyncSession, expire_on_commit=False
)

# Base declarativa de la cual heredarán todos los modelos ORM del sistema (como UsuarioModelo y RolModelo)
Base = declarative_base()


async def obtener_base_datos():
    """Genera una sesión de base de datos asíncrona por cada solicitud HTTP.

    Yields:
        AsyncSession: Sesión activa de base de datos para realizar operaciones.
    """
    # Abre una sesión asíncrona asegurando su cierre automático al finalizar la petición
    async with SesionLocalAsync() as sesion:
        yield sesion
