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

from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.database import SesionLocalAsync, obtener_base_datos
from app.error_handlers import registrar_manejadores
from app.errors import PROBLEM_MEDIA_TYPE, AppError, ErrorCode
from app.logger import configurar_logger
from app.routers import admin, auth, machine, me, scan
from app.security.arranque import verificar_llaves
from app.services import inactividad

logger = configurar_logger()


class LimiteCuerpoMiddleware(BaseHTTPMiddleware):
    """Rechaza peticiones cuyo cuerpo supere ``MAX_BODY_BYTES`` con un 413.

    Cuenta los bytes reales del stream para no dejarse engañar por un
    ``Content-Length`` falso o un ``Transfer-Encoding: chunked``.
    """

    async def dispatch(self, request: Request, call_next):
        """Valida el tamaño del cuerpo antes de pasarlo al router."""
        try:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > settings.max_body_bytes:
                        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE)
                except ValueError:
                    raise AppError(ErrorCode.BAD_REQUEST, detail="Content-Length inválido.") from None

            if not content_length or request.headers.get("transfer-encoding") == "chunked":
                body = b""
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > settings.max_body_bytes:
                        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE)
                
                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                
                request._receive = receive

            return await call_next(request)
        except AppError as exc:
            # Como es un middleware, tenemos que armar la respuesta RFC 9457 manualmente
            spec = exc.code.spec
            return JSONResponse(
                status_code=exc.status or spec.status,
                media_type=PROBLEM_MEDIA_TYPE,
                content={
                    "type": exc.code.type_uri,
                    "title": exc.title or spec.title,
                    "status": exc.status or spec.status,
                    "code": exc.code.value,
                    "detail": exc.detail or spec.detail,
                    "instance": request.url.path,
                },
            )


class CabecerasSeguridadMiddleware(BaseHTTPMiddleware):
    """Agrega las cabeceras de seguridad del SRS §12.9 a cada respuesta."""

    async def dispatch(self, request: Request, call_next):
        """Ejecuta la petición y añade las cabeceras a la respuesta."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
    """Valida la configuración y arranca la tarea de inactividad."""
    verificar_llaves()
    tarea = None
    if settings.tarea_inactividad_activa:
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
    """Liveness: responde sin tocar la base de datos ni escribir en el log."""
    return {"status": "ok", "service": "backend"}


@app.get("/readyz")
async def verificar_listo(db: AsyncSession = Depends(obtener_base_datos)) -> dict:
    """Readiness: comprueba la conexión a la base de datos."""
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
