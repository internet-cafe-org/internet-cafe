"""Router para los endpoints del portal del estudiante (BE-11, HU-13).

Expone cuatro endpoints bajo el prefijo /api/v1/me:
  - GET  /me                   → perfil del usuario autenticado
  - GET  /me/sessions          → historial de sesiones paginado
  - GET  /me/sessions/active   → sesión activa en curso
  - POST /me/sessions/{id}/end → cierre de sesión desde el portal web

Todos los endpoints requieren un Bearer token válido (ES256) en el header
Authorization. Los datos personales sensibles (nombre, código) solo se
devuelven en la forma que el SRS autoriza: nombre completo y código enmascarado.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.dependencies import get_current_user
from app.services import student as svc
from app.services.challenges import mask_student_code

router = APIRouter(prefix="/me", tags=["estudiante"])


# ---------------------------------------------------------------------------
# Schemas de respuesta (Pydantic)
# ---------------------------------------------------------------------------

class PerfilResponse(BaseModel):
    """Datos del perfil del estudiante autenticado."""
    id: uuid.UUID
    full_name: str
    student_code_masked: str
    role: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MaquinaEnSesion(BaseModel):
    """Información básica de la máquina asociada a una sesión."""
    id: uuid.UUID
    code: str
    lab: str | None = None


class SesionResumen(BaseModel):
    """Resumen de una sesión de acceso para el historial."""
    id: uuid.UUID
    machine: MaquinaEnSesion
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None


class HistorialResponse(BaseModel):
    """Respuesta paginada del historial de sesiones."""
    page: int
    page_size: int
    total: int
    items: list[SesionResumen]


class SesionActivaResponse(BaseModel):
    """Sesión de acceso actualmente en curso."""
    id: uuid.UUID
    machine: MaquinaEnSesion
    started_at: datetime
    last_heartbeat_at: datetime


class CierreResponse(BaseModel):
    """Confirmación del cierre de sesión."""
    id: uuid.UUID
    ended_at: datetime
    end_reason: str


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _leer_bytes_como_texto(campo: bytes | None, fallback: str = "") -> str:
    """Convierte un campo _ct (bytes) a texto plano.

    En la implementación actual del MVP los datos se almacenan como bytes
    UTF-8 sin cifrado real (el cifrado por columna vendrá en la siguiente
    iteración). Por eso simplemente hacemos decode, igual que en challenges.py.
    """
    if not campo:
        return fallback
    try:
        return campo.decode("utf-8", errors="ignore") or fallback
    except Exception:
        return fallback


def _serializar_sesion(sesion, maquina, lab) -> SesionResumen:
    """Construye un SesionResumen a partir de los ORM objects."""
    lab_nombre = lab.name if lab else None
    return SesionResumen(
        id=sesion.id,
        machine=MaquinaEnSesion(id=maquina.id, code=maquina.code, lab=lab_nombre),
        started_at=sesion.started_at,
        ended_at=sesion.ended_at,
        end_reason=sesion.end_reason.value if sesion.end_reason else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=PerfilResponse, summary="Perfil del estudiante")
async def obtener_mi_perfil(
    claims: dict = Depends(get_current_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> PerfilResponse:
    """Devuelve los datos del perfil del usuario autenticado.

    El código de estudiante se devuelve enmascarado (ej: 2021****34)
    para cumplir con la política de privacidad (SRS §9.1 / RNF-PRI-02).
    El campo `full_name` se devuelve tal como está registrado en el sistema.

    Returns:
        PerfilResponse con id, full_name, student_code_masked, role, status y created_at.

    Raises:
        401: Si el token no es válido o está ausente.
    """
    user_id = uuid.UUID(claims["sub"])

    try:
        usuario = await svc.obtener_perfil(db, user_id)
    except svc.SesionNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "Usuario no encontrado."},
        )

    nombre = _leer_bytes_como_texto(usuario.full_name_ct, fallback="Estudiante")
    codigo_raw = _leer_bytes_como_texto(usuario.student_code_ct)
    codigo_enmascarado = mask_student_code(codigo_raw) if codigo_raw else "********"

    return PerfilResponse(
        id=usuario.id,
        full_name=nombre,
        student_code_masked=codigo_enmascarado,
        role=usuario.role.value,
        status=usuario.status.value,
        created_at=usuario.created_at,
    )


@router.get(
    "/sessions",
    response_model=HistorialResponse,
    summary="Historial de sesiones del estudiante",
)
async def obtener_historial_sesiones(
    page: int = Query(default=1, ge=1, description="Número de página (comienza en 1)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Sesiones por página"),
    claims: dict = Depends(get_current_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> HistorialResponse:
    """Devuelve el historial de sesiones de acceso del estudiante, paginado.

    Incluye sesiones terminadas y la sesión activa (si existe), ordenadas
    de más reciente a más antigua.

    Query params:
        page: Número de página (mínimo 1).
        page_size: Registros por página (mínimo 1, máximo 100).

    Returns:
        HistorialResponse con page, page_size, total e items.

    Raises:
        401: Si el token no es válido o está ausente.
    """
    user_id = uuid.UUID(claims["sub"])
    filas, total = await svc.obtener_sesiones_paginadas(db, user_id, page, page_size)

    items = [_serializar_sesion(s, m, l) for s, m, l in filas]

    return HistorialResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )


@router.get(
    "/sessions/active",
    response_model=SesionActivaResponse,
    summary="Sesión activa del estudiante",
)
async def obtener_sesion_activa(
    claims: dict = Depends(get_current_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> SesionActivaResponse:
    """Devuelve la sesión de acceso activa del estudiante, si existe.

    Una sesión es 'activa' cuando ended_at es NULL en la base de datos.
    Puede usarse desde el portal para mostrar en qué máquina está conectado
    el estudiante y desde cuándo.

    Returns:
        SesionActivaResponse con id, machine, started_at y last_heartbeat_at.

    Raises:
        401: Si el token no es válido.
        404: Si el estudiante no tiene ninguna sesión activa en este momento.
    """
    user_id = uuid.UUID(claims["sub"])
    sesion = await svc.obtener_sesion_activa(db, user_id)

    if sesion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_ACTIVE_SESSION",
                "message": "El estudiante no tiene ninguna sesión activa.",
            },
        )

    # Cargamos la máquina para armar la respuesta
    from sqlalchemy import select
    from app.models import Lab, Machine

    maq_res = await db.execute(
        select(Machine, Lab)
        .outerjoin(Lab, Machine.lab_id == Lab.id)
        .where(Machine.id == sesion.machine_id)
    )
    fila = maq_res.one_or_none()
    if fila is None:
        raise HTTPException(status_code=500, detail="Error interno: máquina no encontrada.")

    maquina, lab = fila
    lab_nombre = lab.name if lab else None

    return SesionActivaResponse(
        id=sesion.id,
        machine=MaquinaEnSesion(id=maquina.id, code=maquina.code, lab=lab_nombre),
        started_at=sesion.started_at,
        last_heartbeat_at=sesion.last_heartbeat_at,
    )


@router.post(
    "/sessions/{session_id}/end",
    response_model=CierreResponse,
    summary="Cerrar sesión desde el portal web",
)
async def cerrar_mi_sesion(
    session_id: uuid.UUID,
    claims: dict = Depends(get_current_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> CierreResponse:
    """Cierra la sesión de acceso identificada por session_id.

    El estudiante solo puede cerrar sus propias sesiones. Si intenta cerrar
    la sesión de otro usuario, recibe 403. Si la sesión ya estaba cerrada,
    recibe 409 (conflicto) para evitar dobles cierres accidentales.

    La razón de cierre queda registrada como 'user_logout_web' en la BD,
    que permite distinguir este evento en auditorías y reportes.

    Args:
        session_id: UUID de la sesión a cerrar.

    Returns:
        CierreResponse con id, ended_at y end_reason.

    Raises:
        401: Si el token no es válido.
        403: Si la sesión pertenece a otro usuario.
        404: Si la sesión no existe.
        409: Si la sesión ya estaba cerrada.
    """
    user_id = uuid.UUID(claims["sub"])

    try:
        sesion = await svc.cerrar_sesion(db, session_id, user_id)
    except svc.SesionNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "message": "La sesión no existe."},
        )
    except svc.SesionDeOtroUsuarioError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SESSION_FORBIDDEN",
                "message": "No puedes cerrar la sesión de otro usuario.",
            },
        )
    except svc.SesionYaTerminadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SESSION_ALREADY_ENDED",
                "message": "La sesión ya fue cerrada anteriormente.",
            },
        )

    return CierreResponse(
        id=sesion.id,
        ended_at=sesion.ended_at,
        end_reason=sesion.end_reason.value,
    )
