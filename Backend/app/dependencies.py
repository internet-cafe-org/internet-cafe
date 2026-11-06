"""Dependencias compartidas para los routers de FastAPI.

Aquí viven las funciones que FastAPI inyecta en los endpoints con Depends().
La más importante es get_current_user, que valida el token JWT y devuelve
los datos del usuario autenticado para que el endpoint los use directamente.
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.jwt import InvalidTokenError, TokenExpiredError, verify_access_token

# HTTPBearer extrae automáticamente el token del header "Authorization: Bearer <token>"
# auto_error=False nos permite devolver un 401 con cuerpo personalizado en vez del default
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Valida el JWT del header Authorization y devuelve los claims del usuario.

    Esta función se usa como dependencia en cualquier endpoint que requiera
    que el usuario esté autenticado. Extrae el Bearer token, lo verifica con
    la clave pública ES256 configurada en settings, y retorna el payload.

    Args:
        credentials: Objeto con el esquema y el token extraído por HTTPBearer.

    Returns:
        Diccionario con los claims del token: 'sub' (UUID del usuario), 'role',
        'jti', 'iss', 'aud', 'iat', 'exp'.

    Raises:
        HTTPException 401: Si no hay token, está expirado o es inválido.
    """
    # Si no vino el header Authorization, rechazamos de inmediato
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_MISSING", "message": "Se requiere autenticación."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        claims = verify_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "El token ha expirado."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_INVALID", "message": "El token no es válido."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return claims


def get_current_student(
    claims: dict = Depends(get_current_user),
) -> dict:
    """Extiende get_current_user verificando que el rol sea 'student'.

    Útil para endpoints exclusivos del portal del estudiante que no deben
    ser accesibles con tokens de admin u otros roles.

    Args:
        claims: Claims ya validados por get_current_user.

    Returns:
        Los mismos claims si el rol es 'student'.

    Raises:
        HTTPException 403: Si el rol no es 'student'.
    """
    if claims.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_FORBIDDEN",
                "message": "Esta sección es exclusiva para estudiantes.",
            },
        )
    return claims


def get_user_id(claims: dict = Depends(get_current_user)) -> uuid.UUID:
    """Extrae y convierte el 'sub' del token a UUID.

    Shortcut para endpoints que solo necesitan el UUID del usuario
    sin verificar el rol específico.

    Args:
        claims: Claims ya validados por get_current_user.

    Returns:
        UUID del usuario autenticado.
    """
    return uuid.UUID(claims["sub"])
