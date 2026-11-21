"""Punto de entrada de la API FastAPI.

Crea la aplicación, comprueba las llaves al arrancar, registra los manejadores
de errores RFC 9457 (``app.error_handlers``), los middlewares de endurecimiento
(BE-21) y los routers, y expone los endpoints de salud ``/healthz`` (liveness)
y ``/readyz`` (base de datos).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import SesionLocalAsync, obtener_base_datos
from app.error_handlers import registrar_manejadores
from app.errors import AppError, ErrorCode
from app.logger import configurar_logger
from app.routers import admin, auth, machine, me, scan
from app.security.arranque import verificar_llaves
from app.services import inactividad

logger = configurar_logger()


class LimiteCuerpoMiddleware(BaseHTTPMiddleware):
    """Rechaza peticiones cuyo cuerpo supere ``MAX_BODY_BYTES`` con un 413."""

    async def dispatch(self, request: Request, call_next):
        """Valida ``Content-Length`` antes de pasar la petición al router."""
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "type": f"{settings.errors_base_url}/payload-too-large",
                            "title": "Cuerpo demasiado grande",
                            "status": 413,
                            "code": "PAYLOAD_TOO_LARGE",
                            "detail": (
                                f"El cuerpo supera {settings.max_body_bytes} bytes."
                            ),
                            "instance": request.url.path,
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "type": f"{settings.errors_base_url}/bad-request",
                        "title": "Petición inválida",
                        "status": 400,
                        "code": "BAD_REQUEST",
                        "detail": "Content-Length inválido.",
                        "instance": request.url.path,
                    },
                )
        return await call_next(request)


class CabecerasSeguridadMiddleware(BaseHTTPMiddleware):
    """Agrega las cabeceras de seguridad del SRS §12.9 a cada respuesta."""

    async def dispatch(self, request: Request, call_next):
        """Ejecuta la petición y añade las cabeceras a la respuesta."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


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
    logger.info(
        "API lista",
        extra={"datos": {"evento": "api.arranque", "entorno": settings.app_env}},
    )
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

# BE-21: endurecimiento de la API (SRS §12.9).
# En FastAPI los middlewares se ejecutan en orden inverso al registro, así que
# el último agregado (TrustedHost) es el primero en validar la petición.
app.add_middleware(CabecerasSeguridadMiddleware)
app.add_middleware(LimiteCuerpoMiddleware)
if settings.hosts_permitidos:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.hosts_permitidos,
    )

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