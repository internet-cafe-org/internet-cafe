import asyncio
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
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
from app.security.dependencies import require_machine
from app.services import challenges, events, sesiones

router = APIRouter(prefix="/machine", tags=["machine"])


class ChallengeResponse(BaseModel):
    challenge_id: uuid.UUID
    qr_url: str
    expires_at: datetime
    rotate_after_s: int


class SessionInfo(BaseModel):
    id: uuid.UUID
    status: str = "active"
    started_at: datetime


class UserInfo(BaseModel):
    full_name: str
    student_code_masked: str


class RecentAccessInfo(BaseModel):
    machine_code: str
    lab: str
    started_at: datetime
    ended_at: datetime
    duration_s: int


class ChallengeWaitResponse(BaseModel):
    status: str
    session: SessionInfo | None = None
    user: UserInfo | None = None
    recent_accesses: list[RecentAccessInfo] | None = None


async def get_current_machine(
    x_machine_code: str = Header(...),
    db: AsyncSession = Depends(obtener_base_datos),
) -> Machine:
    """TEMPORAL (hasta SEC-04): busca el equipo por su código.

    Solo la usan `POST /challenges` y `GET /challenges/wait` (contrato v0.1). Los
    endpoints nuevos del contrato v0.2 ya usan `require_machine`.
    """
    machine = (
        await db.execute(select(Machine).where(Machine.code == x_machine_code))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(401, detail={"code": "MACHINE_SIGNATURE_INVALID"})
    return machine


@router.post("/challenges", response_model=ChallengeResponse, status_code=201)
async def crear_reto(
    machine: Machine = Depends(get_current_machine),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ChallengeResponse:
    """Crea un reto QR de un solo uso para el equipo."""
    try:
        reto, token = await challenges.crear_reto(db, machine.id)
    except challenges.MachineNotActiveError:
        raise HTTPException(403, detail={"code": "MACHINE_DISABLED"})
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
    machine: Machine = Depends(get_current_machine),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ChallengeWaitResponse:
    """Espera en long-poll la confirmación de un reto QR para el equipo (SRS §8.1 / BE-06).

    1. Suscribirse al evento en memoria antes de leer la BD.
    2. Si el equipo ya tiene sesión activa, responder 'approved' de inmediato.
    3. Soltar la conexión de base de datos mientras espera (RNF-REN-04).
    4. Esperar hasta timeout segundos a que se notifique el claim en POST /scan/claim.
    5. Responder con 'approved' y los datos de la sesión o 'waiting' por timeout.
    6. En finally, desuscribirse del dispatcher de eventos para evitar fugas de memoria.
    """
    if machine.status != MachineStatus.active:
        raise HTTPException(403, detail={"code": "MACHINE_DISABLED"})

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
    server_time: datetime
    mode: MachineMode
    session_status: Literal["active", "ended", "none"]
    session_id: uuid.UUID | None = None
    end_reason: SessionEndReason | None = None


class CurrentSessionInfo(BaseModel):
    id: uuid.UUID
    status: Literal["active"] = "active"
    started_at: datetime


class CurrentSessionResponse(BaseModel):
    session: CurrentSessionInfo
    user: UserInfo
    recent_accesses: list[RecentAccessInfo]


class EndSessionRequest(BaseModel):
    """Motivo del cierre desde el equipo (SRS §8.3)."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["user_logout_pc", "machine_shutdown"] = "user_logout_pc"


class EndedSessionInfo(BaseModel):
    id: uuid.UUID
    status: Literal["closed"] = "closed"
    ended_at: datetime
    end_reason: SessionEndReason


class EndedSessionResponse(BaseModel):
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
