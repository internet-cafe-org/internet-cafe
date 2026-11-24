"""Endpoints del equipo (``/machine/*``): enrolamiento, QR, long-poll, latido y cierre.

Salvo ``/machine/enroll``, que se autentica con el código de un solo uso, todos
exigen ``require_machine``: hoy la credencial provisional (``X-Machine-Code`` +
``X-Machine-Key``); con SEC-07, la firma RFC 9421. Los routers no cambian al
pasar de una a otra.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SesionLocalAsync, obtener_base_datos
from app.errors import AppError, ErrorCode
from app.models import (
    AuditActorType,
    Machine,
    MachineMode,
    MachineStatus,
    SessionEndReason,
)
from app.security import limites
from app.security.dependencies import require_machine, require_machine_retos
from app.services import challenges, enrolamiento, events, inactividad, sesiones

router = APIRouter(prefix="/machine", tags=["machine"])


class ChallengeResponse(BaseModel):
    """Respuesta de ``POST /machine/challenges``."""

    challenge_id: uuid.UUID
    qr_url: str
    expires_at: datetime
    rotate_after_s: int


class SessionInfo(BaseModel):
    """Sesión aprobada que recibe el equipo en el long-poll."""

    id: uuid.UUID
    status: str = "active"
    started_at: datetime


class UserInfo(BaseModel):
    """Estudiante de la sesión, con el código enmascarado."""

    full_name: str
    student_code_masked: str


class RecentAccessInfo(BaseModel):
    """Acceso reciente del estudiante, para el tablero del equipo."""

    machine_code: str
    lab: str
    started_at: datetime
    ended_at: datetime
    duration_s: int


class ChallengeWaitResponse(BaseModel):
    """Respuesta de ``GET /machine/challenges/wait``: ``approved`` o ``waiting``."""

    status: str
    session: SessionInfo | None = None
    user: UserInfo | None = None
    recent_accesses: list[RecentAccessInfo] | None = None


# =====================================================================================
# SEC-05: enrolamiento con prueba de posesión (SRS §8.4 y §12.4). Ruta pública: el
# equipo todavía no tiene credencial; se autentica con el código de un solo uso.
# =====================================================================================
class JwkP256(BaseModel):
    """Clave pública EC P-256 del equipo (RFC 7517), sin la parte privada."""

    model_config = ConfigDict(extra="forbid")

    kty: Literal["EC"]
    crv: Literal["P-256"]
    x: str = Field(min_length=43, max_length=44)
    y: str = Field(min_length=43, max_length=44)


class JwkRsa(BaseModel):
    """Clave pública RSA del equipo (RFC 7518 §6.3), sin la parte privada.

    Es la clave no exportable del TPM (HU-28, ST-SEC-04): de 2048 a 4096 bits y
    exponente 65537. ``n`` mide 342 caracteres con 2048 bits y 683 con 4096.
    """

    model_config = ConfigDict(extra="forbid")

    kty: Literal["RSA"]
    n: str = Field(min_length=342, max_length=683)
    e: str = Field(min_length=4, max_length=4)


JwkEquipo = Annotated[JwkP256 | JwkRsa, Field(discriminator="kty")]


class EnrollRequest(BaseModel):
    """Cuerpo de ``POST /machine/enroll``."""

    model_config = ConfigDict(extra="forbid")

    enrollment_code: str = Field(min_length=8, max_length=64)
    jwk: JwkEquipo
    # 86 caracteres con ``r||s`` (EC); 342 a 683 con RSA de 2048 a 4096 bits.
    proof: str = Field(min_length=86, max_length=684)
    hostname: str | None = Field(default=None, max_length=63)
    app_version: str | None = Field(default=None, max_length=20)

    @field_validator("jwk")
    @classmethod
    def _clave_valida(cls, jwk: JwkP256 | JwkRsa) -> JwkP256 | JwkRsa:
        """Comprueba que el JWK sea una clave pública válida de su tipo.

        Args:
            jwk: JWK con la forma correcta.

        Returns:
            El mismo JWK si es una clave pública válida.

        Raises:
            ValueError: Si las coordenadas EC no son base64url de 32 bytes o el
                punto no está en la curva, o si la clave RSA no mide entre 2048 y
                4096 bits o su exponente no es 65537 (422 ``VALIDATION_ERROR``).
        """
        enrolamiento.clave_publica_desde_jwk(jwk.model_dump())
        return jwk


class EnrollResponse(BaseModel):
    """Respuesta de ``POST /machine/enroll``. La credencial se muestra una sola vez."""

    machine_id: uuid.UUID
    code: str
    lab: str | None
    mode: MachineMode
    keyid: str
    provisional_credential: str


@router.post("/enroll", response_model=EnrollResponse, status_code=201)
async def enrolar_equipo(
    body: EnrollRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(obtener_base_datos),
) -> EnrollResponse:
    """Registra la clave pública del equipo y le entrega su credencial (SEC-05).

    Args:
        body: Código, JWK y prueba de posesión.
        request: Petición, para el rate limit (SEC-09).
        response: Respuesta, para marcarla como no cacheable.
        db: Sesión de base de datos.

    Returns:
        Equipo, sala, modo, ``keyid`` y la credencial provisional.

    Raises:
        AppError: ``ENROLLMENT_CODE_INVALID`` si el código no existe, se usó o
            venció; ``MACHINE_SIGNATURE_INVALID`` si la prueba no es válida;
            ``MACHINE_DISABLED`` si el equipo está deshabilitado; ``CONFLICT`` si
            otro equipo ya registró la misma clave; ``RATE_LIMITED`` si se
            superó el límite.
    """
    limites.limitar(request, "machine.enroll", cuenta=body.enrollment_code, origen=limites.Origen.EQUIPO)
    try:
        resultado = await enrolamiento.enrolar(
            db,
            codigo=body.enrollment_code,
            jwk=body.jwk.model_dump(),
            prueba=body.proof,
            hostname=body.hostname,
            app_version=body.app_version,
        )
    except enrolamiento.CodigoInvalido:
        raise AppError(ErrorCode.ENROLLMENT_CODE_INVALID) from None
    except enrolamiento.FirmaInvalida:
        raise AppError(ErrorCode.MACHINE_SIGNATURE_INVALID) from None
    except enrolamiento.EquipoDeshabilitado:
        raise AppError(ErrorCode.MACHINE_DISABLED) from None
    except enrolamiento.ClaveEnUso:
        raise AppError(ErrorCode.CONFLICT, "Esa clave ya está registrada por otro equipo.") from None

    response.headers["Cache-Control"] = "no-store"
    return EnrollResponse(
        machine_id=resultado.machine_id,
        code=resultado.code,
        lab=resultado.lab,
        mode=resultado.mode,
        keyid=resultado.keyid,
        provisional_credential=resultado.provisional_credential,
    )


@router.post("/challenges", response_model=ChallengeResponse, status_code=201)
async def crear_reto(
    machine: Machine = Depends(require_machine_retos),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ChallengeResponse:
    """Crea un reto QR de un solo uso para el equipo (máximo 2 vigentes, RN-06).

    Args:
        machine: Equipo autenticado por ``require_machine``.
        db: Sesión de base de datos.

    Returns:
        Id del reto, URL del QR con el token en el fragmento, vencimiento y
        segundos hasta la rotación.

    Raises:
        AppError: ``MACHINE_DISABLED`` si el equipo no está activo.
    """
    try:
        reto, token = await challenges.crear_reto(db, machine.id)
    except challenges.MachineNotActiveError:
        raise AppError(ErrorCode.MACHINE_DISABLED) from None
    await db.commit()
    return ChallengeResponse(
        challenge_id=reto.id,
        qr_url=f"{settings.frontend_base_url}/s#{token}",
        expires_at=reto.expires_at,
        rotate_after_s=challenges.ROTATE_AFTER_S,
    )


@router.get(
    "/challenges/wait",
    response_model=ChallengeWaitResponse,
    response_model_exclude_none=True,
)
async def esperar_reto(
    timeout: int = Query(default=25, ge=1, le=25),
    machine: Machine = Depends(require_machine_retos),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ChallengeWaitResponse:
    """Espera en long-poll la confirmación de un reto QR para el equipo (SRS §8.1 / BE-06).

    1. Suscribirse al evento en memoria antes de leer la BD.
    2. Si el equipo ya tiene sesión activa, responder 'approved' de inmediato.
    3. Soltar la conexión de base de datos mientras espera (RNF-REN-04).
    4. Esperar hasta timeout segundos a que se notifique el claim en POST /scan/claim.
    5. Responder con 'approved' y los datos de la sesión o 'waiting' por timeout.
    6. En finally, desuscribirse del dispatcher de eventos para evitar fugas de memoria.

    Args:
        timeout: Segundos máximos de espera (1 a 25).
        machine: Equipo autenticado por ``require_machine``.
        db: Sesión de base de datos; se cierra antes de esperar.

    Returns:
        ``approved`` con la sesión, el estudiante y sus accesos recientes, o
        ``waiting`` si venció el tiempo.

    Raises:
        AppError: ``MACHINE_DISABLED`` si el equipo no está activo.
    """
    if machine.status != MachineStatus.active:
        raise AppError(ErrorCode.MACHINE_DISABLED)

    # 1. Suscribirse al evento en memoria antes de leer la BD (SRS §8.1)
    event = events.subscribe(machine.id)
    try:
        # 2. Consultar si el equipo ya tiene una sesión activa
        sesion_activa = await challenges.obtener_sesion_activa_equipo(db, machine.id)

        # 3. Soltar la conexión de BD antes de la espera (RNF-REN-04)
        await db.close()

        if sesion_activa is not None:
            return ChallengeWaitResponse(**sesion_activa)

        # 4. Esperar el evento hasta timeout segundos sin conexión de BD
        try:
            await asyncio.wait_for(event.wait(), timeout=float(timeout))
        except asyncio.TimeoutError:
            return ChallengeWaitResponse(status="waiting")

        # 5. Al despertar, obtener el payload notificado
        payload = events.get_event_payload(machine.id)
        if payload:
            return ChallengeWaitResponse(**payload)

        # Fallback si el payload no estuviera en memoria
        async with SesionLocalAsync() as fallback_db:
            recuperada = await challenges.obtener_sesion_activa_equipo(fallback_db, machine.id)
            if recuperada:
                return ChallengeWaitResponse(**recuperada)
        return ChallengeWaitResponse(status="waiting")
    finally:
        # 6. Siempre desuscribirse para prevenir fugas de memoria
        events.unsubscribe(machine.id, event)


# =====================================================================================
# Contrato v0.2 (BE-18): latido con `mode`, sesión actual y cierre desde el equipo.
# Autenticación: `require_machine` (credencial provisional hasta la firma RFC 9421).
# =====================================================================================
class HeartbeatRequest(BaseModel):
    """Cuerpo opcional del latido. Rechaza campos desconocidos (VALIDATION_ERROR)."""

    model_config = ConfigDict(extra="forbid")

    # Sesión que el equipo cree tener abierta; permite informarle un cierre remoto.
    session_id: uuid.UUID | None = None


class HeartbeatResponse(BaseModel):
    """Respuesta del latido: hora del servidor, modo y estado de la sesión."""

    server_time: datetime
    mode: MachineMode
    session_status: Literal["active", "ended", "none"]
    session_id: uuid.UUID | None = None
    end_reason: SessionEndReason | None = None


class CurrentSessionInfo(BaseModel):
    """Sesión abierta del equipo."""

    id: uuid.UUID
    status: Literal["active"] = "active"
    started_at: datetime


class CurrentSessionResponse(BaseModel):
    """Respuesta de ``GET /machine/sessions/current``."""

    session: CurrentSessionInfo
    user: UserInfo
    recent_accesses: list[RecentAccessInfo]


class EndSessionRequest(BaseModel):
    """Motivo del cierre desde el equipo (SRS §8.3)."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["user_logout_pc", "machine_shutdown"] = "user_logout_pc"


class EndedSessionInfo(BaseModel):
    """Sesión cerrada desde el equipo."""

    id: uuid.UUID
    status: Literal["closed"] = "closed"
    ended_at: datetime
    end_reason: SessionEndReason


class EndedSessionResponse(BaseModel):
    """Respuesta de ``POST /machine/sessions/current/end``."""

    session: EndedSessionInfo


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    response_model_exclude_none=True,
)
async def latido(
    body: HeartbeatRequest | None = None,
    machine: Machine = Depends(require_machine),
    db: AsyncSession = Depends(obtener_base_datos),
) -> HeartbeatResponse:
    """Latido del equipo (cada 60 s): devuelve su modo y el estado de su sesión.

    Fija `last_seen_at` y, si hay sesión abierta, `last_heartbeat_at` con la hora del
    servidor (RN-01). Un equipo que no está `active` no puede enviar latidos (RN-08).
    """
    if machine.status != MachineStatus.active:
        raise AppError(ErrorCode.MACHINE_DISABLED)
    ahora = challenges.ahora()
    estado = await sesiones.registrar_latido(
        db, machine.id, ahora, body.session_id if body else None
    )
    await db.commit()
    if estado.get("session_status") == "active":
        inactividad.marcar_actividad()
    return HeartbeatResponse(server_time=ahora, mode=machine.mode, **estado)


@router.get(
    "/sessions/current",
    response_model=CurrentSessionResponse,
    responses={204: {"description": "El equipo no tiene sesión abierta."}},
)
async def sesion_actual(
    machine: Machine = Depends(require_machine),
    db: AsyncSession = Depends(obtener_base_datos),
):
    """Sesión abierta del equipo, con el estudiante enmascarado y sus accesos recientes."""
    datos = await sesiones.obtener_sesion_actual(db, machine.id)
    if datos is None:
        return Response(status_code=204)
    return CurrentSessionResponse(**datos)


@router.post("/sessions/current/end", response_model=EndedSessionResponse)
async def cerrar_sesion_actual(
    body: EndSessionRequest | None = None,
    machine: Machine = Depends(require_machine),
    db: AsyncSession = Depends(obtener_base_datos),
) -> EndedSessionResponse:
    """Cierra desde el equipo la sesión abierta (`user_logout_pc` o `machine_shutdown`)."""
    motivo = SessionEndReason(body.reason if body else "user_logout_pc")
    ahora = challenges.ahora()
    session_id = await sesiones.cerrar_sesion_de_equipo(db, machine.id, motivo, ahora)
    if session_id is None:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, detail="El equipo no tiene una sesión abierta.")
    await sesiones.auditar_cierre(
        db,
        actor_type=AuditActorType.machine,
        actor_id=machine.id,
        session_id=session_id,
        motivo=motivo,
    )
    await db.commit()
    return EndedSessionResponse(
        session=EndedSessionInfo(id=session_id, ended_at=ahora, end_reason=motivo)
    )
