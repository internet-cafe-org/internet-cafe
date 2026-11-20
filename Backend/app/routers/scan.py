"""Escaneo del QR desde el celular: vista previa y confirmación (BE-07a y BE-07b).

Ambos endpoints exigen el access token del estudiante (``require_user``). El
usuario sale siempre del token, nunca de una cabecera ni del cuerpo (SEC-04).
Los errores salen con el catálogo RFC 9457 de ``app.errors``.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.errors import AppError, ErrorCode
from app.security import limites
from app.security.dependencies import CurrentUser, require_user
from app.services import challenges, inactividad

router = APIRouter(prefix="/scan", tags=["scan"])

# Excepciones del servicio de retos y el código del catálogo que les corresponde.
_ERRORES_RETO: dict[type[Exception], ErrorCode] = {
    challenges.ChallengeNotFoundError: ErrorCode.CHALLENGE_NOT_FOUND,
    challenges.ChallengeExpiredError: ErrorCode.CHALLENGE_EXPIRED,
    challenges.ChallengeAlreadyUsedError: ErrorCode.CHALLENGE_ALREADY_USED,
    challenges.MachineBusyError: ErrorCode.MACHINE_BUSY,
    challenges.MachineNotActiveError: ErrorCode.MACHINE_DISABLED,
}


# --- Esquemas según el SRS §10.4 ---


class TokenReto(BaseModel):
    """Cuerpo de ``/scan/preview`` y ``/scan/claim``: el token del fragmento del QR."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)


class MachinePreview(BaseModel):
    """Equipo y sala que el estudiante va a confirmar."""

    code: str
    lab: str


class ActiveSessionPreview(BaseModel):
    """Sesión abierta del estudiante en otro equipo, si la tiene."""

    machine_code: str


class PreviewResponse(BaseModel):
    """Respuesta de ``POST /scan/preview``."""

    machine: MachinePreview
    expires_at: datetime
    active_session: ActiveSessionPreview | None


class MachineClaimInfo(BaseModel):
    """Equipo de la sesión creada."""

    id: uuid.UUID
    code: str
    lab: str


class SessionClaimInfo(BaseModel):
    """Sesión creada o recuperada por la confirmación."""

    id: uuid.UUID
    status: str
    started_at: datetime
    machine: MachineClaimInfo


class ClaimResponse(BaseModel):
    """Respuesta de ``POST /scan/claim``."""

    session: SessionClaimInfo


def _error_de_reto(exc: Exception) -> AppError:
    """Traduce una excepción del servicio de retos al error del catálogo.

    Args:
        exc: Excepción lanzada por ``app.services.challenges``.

    Returns:
        El ``AppError`` con el código RFC 9457 que corresponde.
    """
    codigo = next(c for tipo, c in _ERRORES_RETO.items() if isinstance(exc, tipo))
    return AppError(codigo)


@router.post("/preview", response_model=PreviewResponse, status_code=200)
async def ver_vista_previa(
    payload: TokenReto,
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> PreviewResponse:
    """Muestra el equipo escaneado antes de confirmar el acceso; no consume el reto.

    Args:
        payload: Token del QR.
        usuario: Estudiante autenticado por el access token.
        db: Sesión de base de datos.

    Returns:
        Equipo, sala, vencimiento del reto y sesión activa del estudiante.

    Raises:
        AppError: ``CHALLENGE_NOT_FOUND``, ``CHALLENGE_EXPIRED`` o
            ``CHALLENGE_ALREADY_USED`` según el estado del reto.
    """
    try:
        return await challenges.obtener_vista_previa(db, payload.token, usuario.id)
    except tuple(_ERRORES_RETO) as exc:
        raise _error_de_reto(exc) from None


@router.post("/claim", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def confirmar_claim(
    payload: TokenReto,
    request: Request,
    response: Response,
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ClaimResponse:
    """Confirma el acceso al equipo escaneado y crea la sesión.

    Es idempotente para el mismo estudiante: si repite la confirmación del mismo
    reto recibe 200 con la sesión ya creada en vez de 201.

    Args:
        payload: Token del QR.
        request: Petición, para el rate limit (SEC-09).
        response: Respuesta, para cambiar el estado a 200 en un reintento.
        usuario: Estudiante autenticado por el access token.
        db: Sesión de base de datos.

    Returns:
        La sesión creada (o la existente, en un reintento) con su equipo.

    Raises:
        AppError: ``CHALLENGE_NOT_FOUND``, ``CHALLENGE_EXPIRED``,
            ``CHALLENGE_ALREADY_USED``, ``MACHINE_BUSY``, ``MACHINE_DISABLED`` o
            ``RATE_LIMITED``.
    """
    limites.limitar(request, "scan.claim", cuenta=str(usuario.id))
    try:
        sesion, machine, lab_name, is_idempotent = await challenges.reclamar_reto_qr(
            db=db,
            token=payload.token,
            user_id=usuario.id,
        )
    except tuple(_ERRORES_RETO) as exc:
        raise _error_de_reto(exc) from None

    inactividad.marcar_actividad()
    if is_idempotent:
        response.status_code = status.HTTP_200_OK

    return ClaimResponse(
        session=SessionClaimInfo(
            id=sesion.id,
            status="active" if sesion.ended_at is None else "closed",
            started_at=sesion.started_at,
            machine=MachineClaimInfo(id=machine.id, code=machine.code, lab=lab_name),
        )
    )
