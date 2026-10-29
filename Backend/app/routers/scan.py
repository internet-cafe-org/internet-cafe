import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
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


# NOTA DE SEGURIDAD: Simulamos temporalmente un usuario autenticado (user_id) 
# hasta que se acople la validación del JWT del estudiante.
@router.post("/preview", response_model=PreviewResponse, status_code=200)
async def ver_vista_previa(
    payload: PreviewRequest,
    db: AsyncSession = Depends(obtener_base_datos),
) -> PreviewResponse:
    """Muestra la información del equipo escaneado antes de confirmar el acceso."""
    
    # ID estático temporal para pruebas de estudiante simulado
    ESTUDIANTE_MOCK_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
    
    try:
        datos = await challenges.obtener_vista_previa(db, payload.token, ESTUDIANTE_MOCK_ID)
        return datos
    except challenges.ChallengeNotFoundError:
        raise HTTPException(404, detail={"code": "CHALLENGE_NOT_FOUND"})
    except challenges.ChallengeExpiredError:
        raise HTTPException(410, detail={"code": "CHALLENGE_EXPIRED"})
    except challenges.ChallengeAlreadyUsedError:
        raise HTTPException(409, detail={"code": "CHALLENGE_ALREADY_USED"})
