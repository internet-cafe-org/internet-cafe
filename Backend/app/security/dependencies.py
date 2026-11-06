"""Dependencias de autorización de FastAPI (SEC-04).

- require_user: valida el access token ES256 y devuelve el usuario.
- require_admin: exige además role = admin.
- require_machine: autentica al equipo con una credencial PROVISIONAL.

La credencial provisional se compara por hash: la base solo guarda el
SHA-256 (hex) en machines.key_thumbprint. Cuando exista la firma RFC 9421,
solo se reemplaza require_machine; los routers no cambian.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.jwt import InvalidTokenError, TokenExpiredError, verify_access_token
from app.models import Machine, MachineStatus, UserRole

_bearer = HTTPBearer(auto_error=False)
_HASH_VACIO = "0" * 64


@dataclass(frozen=True)
class CurrentUser:
    """Usuario autenticado, tomado de los claims del access token."""

    id: uuid.UUID
    role: UserRole


def hash_machine_credential(credential: str) -> str:
    """SHA-256 en hex (64 caracteres) de la credencial del equipo."""
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def _error(status: int, code: str) -> HTTPException:
    return HTTPException(status, detail={"code": code})


async def require_user(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Exige un access token válido en Authorization: Bearer."""
    if credenciales is None:
        raise _error(401, "AUTH_INVALID_CREDENTIALS")
    try:
        claims = verify_access_token(credenciales.credentials)
    except TokenExpiredError:
        raise _error(401, "AUTH_TOKEN_EXPIRED")
    except InvalidTokenError:
        raise _error(401, "AUTH_INVALID_CREDENTIALS")

    try:
        return CurrentUser(id=uuid.UUID(claims["sub"]), role=UserRole(claims["role"]))
    except ValueError:
        raise _error(401, "AUTH_INVALID_CREDENTIALS")


async def require_admin(usuario: CurrentUser = Depends(require_user)) -> CurrentUser:
    """Exige un usuario con rol admin."""
    if usuario.role != UserRole.admin:
        raise _error(403, "FORBIDDEN")
    return usuario


async def require_machine(
    x_machine_code: str | None = Header(default=None),
    x_machine_key: str | None = Header(default=None),
    db: AsyncSession = Depends(obtener_base_datos),
) -> Machine:
    """Autentica al equipo por código + credencial provisional (comparada por hash)."""
    if not x_machine_code or not x_machine_key:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")

    machine = (
        await db.execute(select(Machine).where(Machine.code == x_machine_code))
    ).scalar_one_or_none()

    presentado = hash_machine_credential(x_machine_key)
    guardado = machine.key_thumbprint if machine is not None else None
    # Se compara siempre, para que el tiempo de respuesta no delate si el equipo existe.
    coincide = hmac.compare_digest(presentado, guardado or _HASH_VACIO)

    if machine is None or guardado is None or not coincide:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    if machine.status == MachineStatus.disabled:
        raise _error(403, "MACHINE_DISABLED")
    return machine
