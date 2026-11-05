"""Punto de entrada principal para la aplicación FastAPI.

Inicializa la instancia del servidor, integra las configuraciones de entorno,
y expone los endpoints de salud (/healthz) y disponibilidad de base de datos (/readyz).
"""


from app.routers import auth, machine, scan

from app.routers import admin, machine, me, scan

from app.config import settings
from app.database import obtener_base_datos
from app.error_handlers import registrar_manejadores
from app.logger import configurar_logger
from app.problem_details import (
    manejar_error_http,
    manejar_error_validacion,
    manejar_error_general,
)
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Inicializa el sistema de registros JSON
logger = configurar_logger()

# Inicializa la aplicación FastAPI
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Servidor API REST para la gestión del sistema de internet café.",
)

# Registra los manejadores globales de errores RFC 9457
app.add_exception_handler(
    StarletteHTTPException,
    manejar_error_http,
)
app.add_exception_handler(
    RequestValidationError,
    manejar_error_validacion,
)
app.add_exception_handler(
    Exception,
    manejar_error_general,
)

# Manejador RFC 9457 completo (QA-03); se registra al final para que prevalezca
registrar_manejadores(app)

# Registra las rutas de la API
app.include_router(machine.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")

app.include_router(auth.router, prefix="/api/v1")

app.include_router(me.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")



@app.get("/healthz")
def verificar_salud() -> dict:
    """Verifica el estado operativo básico del servidor backend."""
    logger.info("Verificación de salud (/healthz) ejecutada con éxito.")
    return {"status": "ok", "service": "backend"}


@app.get("/readyz")
async def verificar_listo(db: AsyncSession = Depends(obtener_base_datos)) -> dict:
    """Verifica la disponibilidad del sistema y la conexión a la BD."""
    try:
        await db.execute(text("SELECT 1"))
        logger.info("Verificación de disponibilidad (/readyz) exitosa.")
        return {"status": "ready", "database": "connected"}
    except Exception:
        logger.error("Fallo en la conexión a la base de datos.")
        return JSONResponse(
            status_code=503,
            content={
                "type": "about:blank",
                "title": "Servicio no disponible",
                "status": 503,
                "detail": "La base de datos no está disponible.",
                "code": "DATABASE_UNAVAILABLE",
            },
            media_type="application/problem+json",
        )
