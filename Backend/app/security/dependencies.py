"""Dependencias de autorización de FastAPI (SEC-04).

- require_user: valida el access token ES256 y devuelve el usuario.
- require_admin: exige además role = admin.
- require_machine: autentica al equipo según MACHINE_AUTH_MODE: firma RFC 9421
  (SEC-07, ``app.security.firma``) o credencial provisional (``dual``/``token``).

La credencial provisional se compara por hash: la base solo guarda el
SHA-256 (hex) en machines.credential_hash (SEC-05). SEC-14 la retira cuando la
firma sea obligatoria; los routers no cambian.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import InvalidTokenError, TokenExpiredError, verify_access_token
from app.logger import obtener_logger
from app.models import Machine, MachineStatus, UserRole
from app.security import firma

_bearer = HTTPBearer(auto_error=False)
_logger = obtener_logger("equipos")
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
    x_machine_code: str | None = Header(default=None),
    x_machine_key: str | None = Header(default=None),
    db: AsyncSession = Depends(obtener_base_datos),
) -> Machine:
    """Autentica al equipo según ``MACHINE_AUTH_MODE`` (SEC-07, HU-19).

    - ``token``: solo la credencial provisional (``X-Machine-Code`` + ``X-Machine-Key``).
    - ``dual``: si llega la firma RFC 9421 debe ser válida; si no, se acepta la
      credencial. Es el modo de transición mientras Desktop integra la firma.
    - ``signature``: solo la firma.

    Args:
        request: Petición entrante (cabeceras de firma y cuerpo).
        x_machine_code: Código del equipo, para la credencial provisional.
        x_machine_key: Credencial provisional.
        db: Sesión de base de datos.

    Returns:
        El equipo autenticado.

    Raises:
        HTTPException: 401 ``MACHINE_SIGNATURE_INVALID`` o ``MACHINE_CLOCK_SKEW``;
            403 ``MACHINE_DISABLED`` si el equipo está deshabilitado.
    """
    modo = settings.machine_auth_mode
    if modo == "signature" or (modo == "dual" and firma.trae_firma(request)):
        return await _por_firma(request, db)
    return await _por_credencial(x_machine_code, x_machine_key, db)


async def require_machine_retos(
    request: Request,
    x_machine_code: str | None = Header(default=None),
    x_machine_key: str | None = Header(default=None),
    db: AsyncSession = Depends(obtener_base_datos),
) -> Machine:
    """Autenticación de ``/machine/challenges`` y ``/wait`` con la salida transitoria.

    Igual que ``require_machine``, salvo que con ``RETOS_ACEPTAN_SOLO_CODIGO=true``
    (y nunca con ``APP_ENV=prod``) acepta una petición que solo trae
    ``X-Machine-Code``, como hacía la API antes del arreglo. Existe para no dejar
    sin QR al escritorio actual mientras se actualiza; cada uso queda en el log.

    Args:
        request: Petición entrante.
        x_machine_code: Código del equipo.
        x_machine_key: Credencial provisional, si viene.
        db: Sesión de base de datos.

    Returns:
        El equipo autenticado.

    Raises:
        HTTPException: Los mismos errores que ``require_machine``.
    """
    solo_codigo = x_machine_code and not x_machine_key and not firma.trae_firma(request)
    if solo_codigo and settings.retos_aceptan_solo_codigo and settings.app_env != "prod":
        machine = (
            await db.execute(select(Machine).where(Machine.code == x_machine_code))
        ).scalar_one_or_none()
        if machine is None:
            raise _error(401, "MACHINE_SIGNATURE_INVALID")
        if machine.status == MachineStatus.disabled:
            raise _error(403, "MACHINE_DISABLED")
        if machine.status != MachineStatus.active:
            raise _error(401, "MACHINE_SIGNATURE_INVALID")

        _logger.warning(
            "Reto pedido solo con X-Machine-Code (salida transitoria)",
            extra={"datos": {"evento": "machine.retos_solo_codigo", "machine_id": str(machine.id)}},
        )
        return machine
    return await require_machine(request, x_machine_code, x_machine_key, db)


async def _por_firma(request: Request, db: AsyncSession) -> Machine:
    """Autentica al equipo por su firma RFC 9421 (SEC-07a y SEC-07b).

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


async def _por_credencial(
    x_machine_code: str | None, x_machine_key: str | None, db: AsyncSession
) -> Machine:
    """Autentica al equipo por código + credencial provisional (comparada por hash).

    TRANSITORIO: SEC-14 retira este camino cuando la firma sea obligatoria.

    Args:
        x_machine_code: Código del equipo.
        x_machine_key: Credencial provisional.
        db: Sesión de base de datos.

    Returns:
        El equipo autenticado.

    Raises:
        HTTPException: 401 ``MACHINE_SIGNATURE_INVALID``; 403 ``MACHINE_DISABLED``.
    """
    if not x_machine_code or not x_machine_key:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")

    machine = (
        await db.execute(select(Machine).where(Machine.code == x_machine_code))
    ).scalar_one_or_none()

    presentado = hash_machine_credential(x_machine_key)
    guardado = machine.credential_hash if machine is not None else None
    # Se compara siempre, para que el tiempo de respuesta no delate si el equipo existe.
    coincide = hmac.compare_digest(presentado, guardado or _HASH_VACIO)

    if machine is None or guardado is None or not coincide:
        raise _error(401, "MACHINE_SIGNATURE_INVALID")
    if machine.status == MachineStatus.disabled:
        raise _error(403, "MACHINE_DISABLED")
    return machine
