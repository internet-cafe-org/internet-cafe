"""Manejadores que convierten toda excepción en `application/problem+json`.

`registrar_manejadores(app)` se llama una vez al crear la app. Los 422 se
arman solo con `loc` y `msg` de Pydantic: nunca con `input` ni `ctx`, para
no devolver ni registrar lo que mandó el cliente (por ejemplo contraseñas).
"""

import uuid
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import (
    PROBLEM_MEDIA_TYPE,
    AppError,
    ErrorCode,
    FieldError,
    ProblemDetail,
)
from app.logger import configurar_logger

logger = configurar_logger()

# Status de HTTPException (lanzadas por Starlette o código antiguo) sin code propio
_CODIGO_POR_STATUS: dict[int, ErrorCode] = {
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


def _problema(
    request: Request,
    code: ErrorCode,
    *,
    status: int | None = None,
    title: str | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Arma la respuesta RFC 9457. `instance` va sin query string."""
    spec = code.spec
    cuerpo = ProblemDetail(
        type=code.type_uri,
        title=title or spec.title,
        status=status or spec.status,
        code=code,
        detail=detail or spec.detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        cuerpo.model_dump(mode="json", exclude_none=True),
        status_code=cuerpo.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def _manejar_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _problema(request, exc.code, detail=exc.detail, headers=exc.headers)


async def _manejar_validacion(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errores = [
        FieldError(
            field=".".join(str(parte) for parte in error.get("loc", ())),
            message=str(error.get("msg", "")),
        )
        for error in exc.errors()
    ]
    return _problema(request, ErrorCode.VALIDATION_ERROR, errors=errores)


async def _manejar_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # Compatibilidad con HTTPException(status, detail={"code": "..."})
    code_enviado = exc.detail.get("code") if isinstance(exc.detail, dict) else None
    if isinstance(code_enviado, str) and code_enviado in ErrorCode.__members__:
        return _problema(request, ErrorCode(code_enviado), headers=exc.headers)

    code = _CODIGO_POR_STATUS.get(exc.status_code)
    if code is not None:
        return _problema(request, code, status=exc.status_code, headers=exc.headers)

    # Status sin entrada en el catálogo: se conserva el status y su frase HTTP
    frase = HTTPStatus(exc.status_code).phrase
    generico = (
        ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
    )
    return _problema(
        request,
        generico,
        status=exc.status_code,
        title=frase,
        detail=frase,
        headers=exc.headers,
    )


async def _manejar_inesperado(request: Request, exc: Exception) -> JSONResponse:
    # Solo el tipo de excepción: el mensaje puede traer datos del cliente o SQL
    request_id = uuid.uuid4().hex
    logger.error(
        f"Error no controlado request_id={request_id} "
        f"method={request.method} path={request.url.path} "
        f"exception={type(exc).__name__}"
    )
    return _problema(
        request, ErrorCode.INTERNAL_ERROR, headers={"X-Request-ID": request_id}
    )


def _openapi_con_problemas(app: FastAPI) -> dict[str, Any]:
    """Cambia el 422 `HTTPValidationError` por defecto por `ProblemDetail`."""
    if app.openapi_schema:
        return app.openapi_schema

    esquema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
    componentes.pop("HTTPValidationError", None)
    componentes.pop("ValidationError", None)
    for nombre, modelo in (
        ("FieldError", FieldError),
        ("ProblemDetail", ProblemDetail),
    ):
        definicion = modelo.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        for nombre_def, sub in definicion.pop("$defs", {}).items():
            componentes.setdefault(nombre_def, sub)
        componentes[nombre] = definicion

    problema = {
        PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
    }
    for operaciones in esquema.get("paths", {}).values():
        for operacion in operaciones.values():
            respuesta = operacion.get("responses", {}).get("422")
            if respuesta is not None:
                respuesta["content"] = problema

    app.openapi_schema = esquema
    return esquema


def registrar_manejadores(app: FastAPI) -> None:
    """Registra los manejadores de errores RFC 9457 y ajusta el OpenAPI."""
    app.add_exception_handler(AppError, _manejar_app_error)
    app.add_exception_handler(RequestValidationError, _manejar_validacion)
    app.add_exception_handler(StarletteHTTPException, _manejar_http)
    app.add_exception_handler(Exception, _manejar_inesperado)
    app.openapi = lambda: _openapi_con_problemas(app)  # type: ignore[method-assign]
