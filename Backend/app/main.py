"""Punto de entrada de la API FastAPI.

Crea la aplicación, comprueba las llaves al arrancar, registra los manejadores
de errores RFC 9457 (``app.error_handlers``) y los routers, y expone los
endpoints de salud ``/healthz`` (liveness) y ``/readyz`` (base de datos).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SesionLocalAsync, obtener_base_datos
from app.error_handlers import registrar_manejadores
from app.errors import AppError, ErrorCode
from app.logger import configurar_logger
from app.routers import admin, auth, machine, me, scan
from app.security.arranque import verificar_llaves
from app.services import inactividad

logger = configurar_logger()


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
    """Valida la configuración y arranca la tarea de inactividad.

    Args:
        _app: La aplicación que arranca.

    Yields:
        Control a FastAPI mientras la API está en marcha.

    Raises:
        LlavesInvalidas: Si faltan las llaves JWT o la del índice ciego; la
            API no arranca (HU-07).
    """
    verificar_llaves()
    tarea = None
    if settings.tarea_inactividad_activa:
        # BE-09b: la actividad en memoria se pierde al reiniciar, así que se barre la base.
        await inactividad.barrido_inicial(SesionLocalAsync)
        tarea = asyncio.create_task(inactividad.tarea_periodica(SesionLocalAsync))
    logger.info("API lista", extra={"datos": {"evento": "api.arranque", "entorno": settings.app_env}})
    try:
        yield
    finally:
        if tarea is not None:
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea


app = FastAPI(
    title=settings.app_name,
    version="0.2.1",
    description="Servidor API REST para la gestión del sistema de internet café.",
    lifespan=ciclo_de_vida,
)

registrar_manejadores(app)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(machine.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")
app.include_router(me.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/healthz")
def verificar_salud() -> dict:
    """Liveness: responde sin tocar la base de datos ni escribir en el log.

    Returns:
        ``{"status": "ok", "service": "backend"}``.
    """
    return {"status": "ok", "service": "backend"}


@app.get("/readyz")
async def verificar_listo(db: AsyncSession = Depends(obtener_base_datos)) -> dict:
    """Readiness: comprueba la conexión a la base de datos.

    Args:
        db: Sesión de base de datos.

    Returns:
        ``{"status": "ready", "database": "connected"}``.

    Raises:
        AppError: 503 ``INTERNAL_ERROR`` si la base no responde.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(
            "La base de datos no responde",
            extra={"datos": {"evento": "readyz.fallo", "excepcion": type(exc).__name__}},
        )
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "La base de datos no está disponible.",
            status=503,
            title="Servicio no disponible",
        ) from None
    return {"status": "ready", "database": "connected"}
