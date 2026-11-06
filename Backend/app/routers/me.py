"""Perfil y sesiones del estudiante autenticado (contrato v0.2 / BE-18, SRS §10.3).

Toda ruta exige un access token válido (`require_user`) y filtra por el dueño en la
propia consulta: una sesión ajena responde igual que una inexistente.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import obtener_base_datos
from app.errors import AppError, ErrorCode
from app.models import (
    AccessSession,
    AuditActorType,
    Lab,
    Machine,
    SessionEndReason,
    User,
    UserRole,
    UserStatus,
)
from app.security.dependencies import CurrentUser, require_user
from app.services import challenges, sesiones

router = APIRouter(prefix="/me", tags=["me"])


class ProfileResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    student_code_masked: str
    role: UserRole
    status: UserStatus


class MySessionItem(BaseModel):
    id: uuid.UUID
    machine_code: str
    lab: str
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: SessionEndReason | None = None
    duration_s: int | None = None


class MySessionsPage(BaseModel):
    items: list[MySessionItem]
    total: int
    limit: int
    offset: int


class ActiveSessionResponse(BaseModel):
    session: MySessionItem | None


class MySessionResponse(BaseModel):
    session: MySessionItem


def _item(sesion: AccessSession, machine_code: str, lab: str | None) -> MySessionItem:
    return MySessionItem(
        id=sesion.id,
        machine_code=machine_code,
        lab=lab or sesiones.LAB_SIN_ASIGNAR,
        started_at=sesion.started_at,
        ended_at=sesion.ended_at,
        end_reason=sesion.end_reason,
        duration_s=sesiones.duracion_s(sesion.started_at, sesion.ended_at),
    )


def _consulta_sesiones(*condiciones: Any):
    """SELECT de sesiones con el código del equipo y el nombre de la sala."""
    return (
        select(AccessSession, Machine.code, Lab.name)
        .join(Machine, Machine.id == AccessSession.machine_id)
        .outerjoin(Lab, Lab.id == Machine.lab_id)
        .where(*condiciones)
    )


@router.get("", response_model=ProfileResponse)
async def perfil(
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ProfileResponse:
    """Perfil del usuario autenticado."""
    fila = (await db.execute(select(User).where(User.id == usuario.id))).scalar_one_or_none()
    if fila is None:
        # Token válido de una cuenta que ya no existe
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)
    if fila.status != UserStatus.active:
        raise AppError(ErrorCode.FORBIDDEN)
    nombre, codigo = sesiones.datos_estudiante(fila)
    return ProfileResponse(
        id=fila.id,
        full_name=nombre,
        email=sesiones.texto_plano(fila.email_ct, ""),
        student_code_masked=codigo,
        role=fila.role,
        status=fila.status,
    )


@router.get("/sessions", response_model=MySessionsPage)
async def historial(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> MySessionsPage:
    """Historial paginado de sesiones propias, de la más reciente a la más antigua."""
    total = (
        await db.execute(
            select(func.count()).select_from(AccessSession).where(AccessSession.user_id == usuario.id)
        )
    ).scalar_one()
    filas = await db.execute(
        _consulta_sesiones(AccessSession.user_id == usuario.id)
        .order_by(AccessSession.started_at.desc(), AccessSession.id)
        .limit(limit)
        .offset(offset)
    )
    return MySessionsPage(
        items=[_item(s, codigo, lab) for s, codigo, lab in filas.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/active", response_model=ActiveSessionResponse)
async def sesion_activa(
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> ActiveSessionResponse:
    """Sesión abierta del usuario o `{"session": null}`."""
    fila = (
        await db.execute(
            _consulta_sesiones(AccessSession.user_id == usuario.id, AccessSession.ended_at.is_(None))
            .order_by(AccessSession.started_at.desc())
            .limit(1)
        )
    ).first()
    if fila is None:
        return ActiveSessionResponse(session=None)
    sesion, codigo, lab = fila
    return ActiveSessionResponse(session=_item(sesion, codigo, lab))


@router.post("/sessions/{session_id}/end", response_model=MySessionResponse)
async def cerrar_sesion_propia(
    session_id: uuid.UUID,
    usuario: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(obtener_base_datos),
) -> MySessionResponse:
    """Cierra una sesión propia desde la web (`user_logout_web`). Idempotente.

    El equipo se entera en su próximo latido (≤ 60 s).
    """
    motivo = SessionEndReason.user_logout_web
    cerrada = await sesiones.cerrar_sesion_abierta(
        db, session_id, motivo, challenges.ahora(), user_id=usuario.id
    )
    if cerrada:
        await sesiones.auditar_cierre(
            db,
            actor_type=AuditActorType.user,
            actor_id=usuario.id,
            session_id=session_id,
            motivo=motivo,
        )
    fila = (
        await db.execute(
            _consulta_sesiones(AccessSession.id == session_id, AccessSession.user_id == usuario.id)
        )
    ).first()
    if fila is None:
        raise AppError(ErrorCode.SESSION_NOT_FOUND)
    await db.commit()
    sesion, codigo, lab = fila
    return MySessionResponse(session=_item(sesion, codigo, lab))
