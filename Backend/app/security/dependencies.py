"""Dependencias de autorización de FastAPI (SEC-04).

- require_user: valida el access token ES256 y devuelve el usuario.
- require_admin: exige además role = admin.
- require_machine: autentica al equipo por la firma RFC 9421 de cada petición
  (SEC-07, ``app.security.firma``). Es el único camino: SEC-14 retiró la
  credencial provisional.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.jwt import InvalidTokenError, TokenExpiredError, verify_access_token
from app.models import Machine, MachineStatus, UserRole
from app.security import firma

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """Usuario autenticado, tomado de los claims del access token."""

    id: uuid.UUID
    role: UserRole


def _error(status: int, code: str) -> HTTPException:
    """Arma el error con el ``code`` del catálogo.

    Se usa ``HTTPException`` con ``detail={"code": ...}`` y no ``AppError``
    para que la dependencia funcione también en apps sin los manejadores del
    proyecto; ``app.error_handlers`` lo convierte en RFC 9457.

    Args:
        status: Código HTTP.
        code: Código estable del catálogo (``app.errors``).

    Returns:
        La excepción lista para lanzar.
    """
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
        raise _error(401, "AUTH_TOKEN_EXPIRED") from None
    except InvalidTokenError:
        raise _error(401, "AUTH_INVALID_CREDENTIALS") from None

    try:
        return CurrentUser(id=uuid.UUID(claims["sub"]), role=UserRole(claims["role"]))
    except ValueError:
        raise _error(401, "AUTH_INVALID_CREDENTIALS") from None


async def require_admin(usuario: CurrentUser = Depends(require_user)) -> CurrentUser:
    """Exige un usuario con rol admin."""
    if usuario.role != UserRole.admin:
        raise _error(403, "FORBIDDEN")
    return usuario


async def require_machine(
    request: Request,
    db: AsyncSession = Depends(obtener_base_datos),
) -> Machine:
    """Autentica al equipo por su firma RFC 9421 (SEC-07, HU-19).

    Las cabeceras de la credencial provisional retirada (``X-Machine-Key``) no se
    leen: una petición sin firma válida responde 401 aunque las traiga.

    Args:
        request: Petición entrante.
        db: Sesión de base de datos.

    Returns:
        El equipo dueño de la clave que firmó.

    Raises:
        HTTPException: 401 ``MACHINE_CLOCK_SKEW`` si el reloj del equipo está
            fuera de la tolerancia; 401 ``MACHINE_SIGNATURE_INVALID`` por
            cualquier otro fallo; 403 ``MACHINE_DISABLED``.
    """
    if not firma.trae_firma(request):
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    try:
        entrada, crudo, base = await firma.preparar(request)
    except firma.RelojDesfasado:
        raise _error(401, "MACHINE_CLOCK_SKEW") from None
    except firma.FirmaInvalida:
        raise _error(401, "MACHINE_SIGNATURE_INVALID") from None

    machine = (
        await db.execute(select(Machine).where(Machine.key_thumbprint == entrada.keyid))
    ).scalar_one_or_none()
    if machine is None or not machine.public_key_jwk:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    if not firma.verificar(machine.public_key_jwk, entrada.alg, base, crudo):
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    # El nonce se registra solo tras una firma válida: un tercero no puede "gastarlo".
    if not firma.nonces.registrar(entrada.keyid, entrada.nonce):
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    if machine.status == MachineStatus.disabled:
        raise _error(403, "MACHINE_DISABLED")
    if machine.status != MachineStatus.active:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    return machine
