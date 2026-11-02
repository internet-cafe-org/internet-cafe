import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.services import challenges

router = APIRouter(prefix="/scan", tags=["scan"])

# --- Esquemas Pydantic según el TRD 10.4 ---
class MachinePreview(BaseModel):
    code: str
    lab: str

class ActiveSessionPreview(BaseModel):
    machine_code: str

class PreviewResponse(BaseModel):
    machine: MachinePreview
    expires_at: datetime
    active_session: ActiveSessionPreview | None

class PreviewRequest(BaseModel):
    token: str

class MachineClaimInfo(BaseModel):
    id: uuid.UUID
    code: str
    lab: str

class SessionClaimInfo(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    machine: MachineClaimInfo

class ClaimResponse(BaseModel):
    session: SessionClaimInfo

class ClaimRequest(BaseModel):
    token: str


async def get_current_user_id(
    x_user_id: uuid.UUID | None = Header(None),
) -> uuid.UUID:
    """TEMPORAL (hasta SEC-04): obtiene el ID del estudiante autenticado."""
    if x_user_id:
        return x_user_id
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@router.post("/preview", response_model=PreviewResponse, status_code=200)
async def ver_vista_previa(
    payload: PreviewRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(obtener_base_datos),
) -> PreviewResponse:
    """Muestra la información del equipo escaneado antes de confirmar el acceso."""
    try:
        datos = await challenges.obtener_vista_previa(db, payload.token, user_id)
        return datos
    except challenges.ChallengeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHALLENGE_NOT_FOUND", "message": "El código QR no existe o es inválido."}
        )
    except challenges.ChallengeExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "CHALLENGE_EXPIRED", "message": "Escanea el código nuevo del equipo."}
        )
    except challenges.ChallengeAlreadyUsedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CHALLENGE_ALREADY_USED", "message": "El código QR ya fue utilizado."}
        )


@router.post("/claim", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def confirmar_claim(
    payload: ClaimRequest,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ClaimResponse:
    """Confirma el acceso al equipo escaneado creando la sesión correspondiente."""
    try:
        sesion, machine, lab_name, is_idempotent = await challenges.reclamar_reto_qr(
            db=db,
            token=payload.token,
            user_id=user_id,
        )

        if is_idempotent:
            response.status_code = status.HTTP_200_OK

        return ClaimResponse(
            session=SessionClaimInfo(
                id=sesion.id,
                status="active" if sesion.ended_at is None else "closed",
                started_at=sesion.started_at,
                machine=MachineClaimInfo(
                    id=machine.id,
                    code=machine.code,
                    lab=lab_name,
                ),
            )
        )
    except challenges.ChallengeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHALLENGE_NOT_FOUND", "message": "El código QR no existe o es inválido."}
        )
    except challenges.ChallengeExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "CHALLENGE_EXPIRED", "message": "Escanea el código nuevo del equipo."}
        )
    except challenges.ChallengeAlreadyUsedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CHALLENGE_ALREADY_USED", "message": "El código QR ya fue utilizado."}
        )
    except challenges.MachineBusyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "MACHINE_BUSY", "message": "El equipo ya tiene una sesión activa."}
        )
    except challenges.MachineNotActiveError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "MACHINE_DISABLED", "message": "El equipo se encuentra deshabilitado."}
        )
