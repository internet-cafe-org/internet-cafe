
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def crear_problem_details(
    status: int,
    title: str,
    detail: str,
    code: str = "HTTP_ERROR",
) -> dict:
    return {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
    }


async def manejar_error_http(
    request: Request,
    error: StarletteHTTPException,
):
    detail = error.detail
    code = "HTTP_ERROR"
    mensaje = "Ha ocurrido un error en la solicitud."

    if isinstance(detail, dict):
        code = detail.get("code", code)
        mensaje = detail.get("message", mensaje)
    elif isinstance(detail, str):
        mensaje = detail

    respuesta = crear_problem_details(
        status=error.status_code,
        title="Error HTTP",
        detail=mensaje,
        code=code,
    )

    return JSONResponse(
        status_code=error.status_code,
        content=respuesta,
        media_type="application/problem+json",
        headers=error.headers,
    )


async def manejar_error_validacion(
    request: Request,
    error: RequestValidationError,
):
    respuesta = crear_problem_details(
        status=422,
        title="Error de validación",
        detail="Los datos enviados no cumplen con el formato requerido.",
        code="VALIDATION_ERROR",
    )

    return JSONResponse(
        status_code=422,
        content=respuesta,
        media_type="application/problem+json",
    )


async def manejar_error_general(
    request: Request,
    error: Exception,
):
    respuesta = crear_problem_details(
        status=500,
        title="Error interno del servidor",
        detail="Ha ocurrido un error inesperado.",
        code="INTERNAL_SERVER_ERROR",
    )

    return JSONResponse(
        status_code=500,
        content=respuesta,
        media_type="application/problem+json",
    )
