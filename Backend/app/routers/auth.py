"""Endpoints de sesion web: refresh rotativo y logout (SEC-03a).

El refresh token viaja solo en una cookie HttpOnly limitada a esta ruta. El
access token se entrega en el cuerpo y el cliente lo guarda en memoria.
"""

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import obtener_base_datos
from app.errors import AppError, ErrorCode
from app.jwt import create_access_token
from app.services import refresh_tokens

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def poner_cookie_refresh(response: Response, token: str) -> None:
    """Pone la cookie del refresh token. El login (SEC-02) tambien la usa."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def borrar_cookie_refresh(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _cabecera_borrado() -> dict[str, str]:
    """Set-Cookie que borra la cookie, para adjuntarlo a un error."""
    temporal = Response()
    borrar_cookie_refresh(temporal)
    return {"set-cookie": temporal.headers["set-cookie"]}


def verificar_origen(origin: str | None = Header(default=None)) -> None:
    """Defensa CSRF extra a SameSite: si hay Origin, debe ser el permitido."""
    permitido = settings.allowed_origin
    if permitido and origin and origin != permitido:
        raise AppError(ErrorCode.FORBIDDEN)


@router.post("/refresh", dependencies=[Depends(verificar_origen)])
async def refrescar(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(obtener_base_datos),
) -> dict:
    """Rota el refresh token y devuelve un access token nuevo."""
    if not refresh_token:
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)

    try:
        rotacion = await refresh_tokens.rotar(
            db, refresh_token, request.headers.get("user-agent")
        )
    except refresh_tokens.RefreshExpirado:
        raise AppError(ErrorCode.AUTH_TOKEN_EXPIRED, headers=_cabecera_borrado())
    except refresh_tokens.RefreshInvalido:
        raise AppError(
            ErrorCode.AUTH_INVALID_CREDENTIALS, headers=_cabecera_borrado()
        )

    acceso = create_access_token(
        subject=str(rotacion.user_id), role=str(rotacion.role.value)
    )
    poner_cookie_refresh(response, rotacion.token)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": acceso,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


@router.post(
    "/logout", status_code=204, dependencies=[Depends(verificar_origen)]
)
async def cerrar_sesion(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(obtener_base_datos),
) -> None:
    """Revoca la sesion y borra la cookie. Siempre responde 204."""
    if refresh_token:
        await refresh_tokens.revocar(db, refresh_token)
    borrar_cookie_refresh(response)