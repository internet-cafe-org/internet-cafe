"""Módulo de configuración de la Base de Datos Asíncrona.

Establece la conexión con el motor de base de datos de forma asíncrona
utilizando SQLAlchemy y SQLAlchemy Asyncio.
"""

from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Crea el motor de base de datos asíncrono utilizando la URL validada en las configuraciones
motor_async = create_async_engine(settings.database_url, echo=True, future=True)

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