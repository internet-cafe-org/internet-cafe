import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import obtener_base_datos
from app.models import Machine
from app.services import challenges

router = APIRouter(prefix="/machine", tags=["machine"])


class ChallengeResponse(BaseModel):
    challenge_id: uuid.UUID
    qr_url: str
    expires_at: datetime
    rotate_after_s: int


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
        # AQUÍ ESTABA EL ERROR (los parámetros estaban invertidos)
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
