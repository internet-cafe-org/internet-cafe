import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SesionLocalAsync, obtener_base_datos
from app.models import Machine, MachineStatus
from app.services import challenges, events

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
    """TEMPORAL (hasta SEC-04): busca el equipo por su código."""
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
