"""Punto de entrada principal para la aplicación FastAPI.

Inicializa la instancia del servidor, integra las configuraciones de entorno,
y expone los endpoints de salud (/healthz) y disponibilidad de base de datos (/readyz).
"""

from app.routers import machine, scan
from app.config import settings
from app.database import obtener_base_datos
from app.logger import configurar_logger
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Inicializa el sistema de registros JSON
logger = configurar_logger()

# Inicializa la aplicación FastAPI utilizando el nombre validado por entorno
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Servidor API REST para la gestión del sistema de internet café.",
)
app.include_router(machine.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")
@app.get("/healthz")
def verificar_salud() -> dict:
    """Verifica el estado operativo básico del servidor backend.

    Returns:
        dict: Diccionario que confirma el estado activo del servicio.
    """
    logger.info("Verificación de salud (/healthz) ejecutada con éxito.")
    return {"status": "ok", "service": "backend"}


@app.get("/readyz")
async def verificar_listo(db: AsyncSession = Depends(obtener_base_datos)) -> dict:
    """Verifica la disponibilidad del sistema y la conectividad con la base de datos.

    Args:
        db (AsyncSession): Sesión asíncrona inyectada de la base de datos.

    Returns:
        dict: Estado de preparación del servicio y conexión a la BD.
    """
    try:
        # Ejecuta una consulta ligera de prueba para validar la conexión al motor
        await db.execute(text("SELECT 1"))
        logger.info("Verificación de disponibilidad (/readyz) exitosa.")
        return {"status": "ready", "database": "connected"}
    except Exception as error:
        logger.error(f"Fallo en la conexión a la base de datos: {error}")
        return {"status": "not_ready", "database": "disconnected"}