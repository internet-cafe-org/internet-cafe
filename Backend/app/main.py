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
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.database import SesionTareas, obtener_base_datos
from app.error_handlers import registrar_manejadores
from app.errors import PROBLEM_MEDIA_TYPE, AppError, ErrorCode
from app.logger import configurar_logger
from app.routers import admin, auth, machine, me, scan
from app.security.arranque import verificar_llaves
from app.services import inactividad, outbox

logger = configurar_logger()


class LimiteCuerpoMiddleware:
    """Limita el tamaño real del cuerpo de las peticiones HTTP.

    Utiliza ASGI directamente para contabilizar los bytes recibidos,
    incluidos los cuerpos enviados mediante Transfer-Encoding: chunked.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int | None = None,
    ) -> None:
        """Inicializa el middleware con el límite máximo del cuerpo.

        Args:
            app: Aplicación ASGI que recibirá las peticiones.
            max_body_bytes: Tamaño máximo permitido en bytes.
        """
        self.app = app
        self.max_body_bytes = max_body_bytes if max_body_bytes is not None else settings.max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Procesa la petición y limita el tamaño de su cuerpo.

        Args:
            scope: Información de la conexión y la petición ASGI.
            receive: Función para recibir mensajes ASGI.
            send: Función para enviar mensajes ASGI.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )

        if content_length is not None:
            try:
                longitud = int(content_length)
                if longitud < 0:
                    raise ValueError
            except ValueError:
                await self._responder_error(
                    scope,
                    receive,
                    send,
                    ErrorCode.BAD_REQUEST,
                    detail="Content-Length inválido.",
                )
                return

            if longitud > self.max_body_bytes:
                await self._responder_error(
                    scope,
                    receive,
                    send,
                    ErrorCode.PAYLOAD_TOO_LARGE,
                )
                return
        # Se almacena el cuerpo antes de entregarlo a la aplicación.
        # Así se puede rechazar una petición chunked sin lanzar una
        # excepción que FastAPI pueda interpretar como error de parsing.
        mensajes = []
        bytes_recibidos = 0

        while True:
            mensaje = await receive()

            if mensaje["type"] == "http.disconnect":
                return

            if mensaje["type"] != "http.request":
                continue

            mensajes.append(mensaje)
            bytes_recibidos += len(mensaje.get("body", b""))

            if bytes_recibidos > self.max_body_bytes:
                await self._responder_error(
                    scope,
                    receive,
                    send,
                    ErrorCode.PAYLOAD_TOO_LARGE,
                )
                return

            if not mensaje.get("more_body", False):
                break

        indice = 0

        async def receive_reproducido():
            nonlocal indice

            if indice < len(mensajes):
                mensaje = mensajes[indice]
                indice += 1
                return mensaje

            return {"type": "http.disconnect"}

        await self.app(scope, receive_reproducido, send)

    @staticmethod
    async def _responder_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        code: ErrorCode,
        detail: str | None = None,
    ) -> None:
        spec = code.spec
        status = spec.status

        response = JSONResponse(
            status_code=status,
            media_type=PROBLEM_MEDIA_TYPE,
            content={
                "type": code.type_uri,
                "title": spec.title,
                "status": status,
                "code": code.value,
                "detail": detail or spec.detail,
                "instance": scope.get("path", "/"),
            },
        )

        await response(scope, receive, send)


class CabecerasSeguridadMiddleware(BaseHTTPMiddleware):
    """Agrega las cabeceras de seguridad del SRS §12.9 a cada respuesta."""

    async def dispatch(self, request: Request, call_next):
        """Ejecuta la petición y añade las cabeceras de seguridad.

        Args:
            request: Petición HTTP recibida.
            call_next: Siguiente middleware o manejador de la aplicación.

        Returns:
            Respuesta HTTP con las cabeceras de seguridad.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Se elimina X-XSS-Protection por ser obsoleta (OWASP recomienda no enviarla)
        return response


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
    """Valida la configuración y arranca las tareas de inactividad y correo.

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
        # Corre con el rol de tareas (svc_jobs, ST-SEC-03).
        await inactividad.barrido_inicial(SesionTareas)
        tarea = asyncio.create_task(inactividad.tarea_periodica(SesionTareas))
    logger.info(
        "API lista",
        extra={"datos": {"evento": "api.arranque", "entorno": settings.app_env}},
    )
    try:
        async with outbox.trabajador_configurado(SesionTareas):
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
# Las cabeceras se registran al final para envolver también las respuestas
# generadas por el límite del cuerpo y TrustedHostMiddleware.
if settings.hosts_permitidos:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.hosts_permitidos,
    )
app.add_middleware(LimiteCuerpoMiddleware)
app.add_middleware(CabecerasSeguridadMiddleware)

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
