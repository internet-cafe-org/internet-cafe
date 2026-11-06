"""Funciones de administración (contrato v0.2 / BE-18, SRS §10.3).

Denegación por defecto: `require_admin` va a nivel de router, así que ninguna ruta
nueva queda abierta por olvido. Las respuestas de administración nunca incluyen
`password_hash`, tokens, claves del equipo ni el código de estudiante completo.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.database import obtener_base_datos
from app.errors import AppError, ErrorCode
from app.models import (
    AccessSession,
    AuditActorType,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineMode,
    MachineStatus,
    SessionEndReason,
    User,
)
from app.security.dependencies import CurrentUser, require_admin
from app.services import challenges, sesiones

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ------------------------------------------------------------------------- esquemas
class LabCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    building: str | None = Field(default=None, max_length=80)


class LabItem(BaseModel):
    id: uuid.UUID
    name: str
    building: str | None = None


class LabsPage(BaseModel):
    items: list[LabItem]
    total: int
    limit: int
    offset: int


class MachinePatch(BaseModel):
    """Edición de un equipo: sala, modo o estado (activar/deshabilitar)."""

    model_config = ConfigDict(extra="forbid")

    lab_id: uuid.UUID | None = None
    mode: MachineMode | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def _al_menos_un_campo(self) -> "MachinePatch":
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo para modificar.")
        return self


class MachineItem(BaseModel):
    id: uuid.UUID
    code: str
    hostname: str | None = None
    lab_id: uuid.UUID | None = None
    lab: str | None = None
    status: MachineStatus
    mode: MachineMode
    app_version: str | None = None
    enrolled_at: datetime | None = None
    last_seen_at: datetime | None = None


class MachinesPage(BaseModel):
    items: list[MachineItem]
    total: int
    limit: int
    offset: int


class AdminUserInfo(BaseModel):
    id: uuid.UUID
    full_name: str
    student_code_masked: str


class AdminSessionItem(BaseModel):
    id: uuid.UUID
    user: AdminUserInfo
    machine_code: str
    lab: str
    started_at: datetime
    last_heartbeat_at: datetime
    ended_at: datetime | None = None
    end_reason: SessionEndReason | None = None
    duration_s: int | None = None


class AdminSessionsPage(BaseModel):
    items: list[AdminSessionItem]
    total: int
    limit: int
    offset: int


class AdminSessionResponse(BaseModel):
    session: AdminSessionItem


# ------------------------------------------------------------------------- ayudas
def _item_sesion(
    sesion: AccessSession, usuario: User | None, machine_code: str, lab: str | None
) -> AdminSessionItem:
    nombre, codigo = sesiones.datos_estudiante(usuario)
    return AdminSessionItem(
        id=sesion.id,
        user=AdminUserInfo(id=sesion.user_id, full_name=nombre, student_code_masked=codigo),
        machine_code=machine_code,
        lab=lab or sesiones.LAB_SIN_ASIGNAR,
        started_at=sesion.started_at,
        last_heartbeat_at=sesion.last_heartbeat_at,
        ended_at=sesion.ended_at,
        end_reason=sesion.end_reason,
        duration_s=sesiones.duracion_s(sesion.started_at, sesion.ended_at),
    )


def _consulta_sesiones(*condiciones: Any):
    return (
        select(AccessSession, User, Machine.code, Lab.name)
        .join(Machine, Machine.id == AccessSession.machine_id)
        .join(User, User.id == AccessSession.user_id)
        .outerjoin(Lab, Lab.id == Machine.lab_id)
        .where(*condiciones)
    )


def _utc(momento: datetime | None) -> datetime | None:
    """Una fecha sin zona horaria se interpreta como UTC (asyncpg exige fechas con zona)."""
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _item_equipo(machine: Machine, lab_name: str | None) -> MachineItem:
    return MachineItem(
        id=machine.id,
        code=machine.code,
        hostname=machine.hostname,
        lab_id=machine.lab_id,
        lab=lab_name,
        status=machine.status,
        mode=machine.mode,
        app_version=machine.app_version,
        enrolled_at=machine.enrolled_at,
        last_seen_at=machine.last_seen_at,
    )


# ------------------------------------------------------------------------- salas
@router.get("/labs", response_model=LabsPage)
async def listar_salas(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(obtener_base_datos),
) -> LabsPage:
    total = (await db.execute(select(func.count()).select_from(Lab))).scalar_one()
    salas = (
        await db.execute(select(Lab).order_by(Lab.name).limit(limit).offset(offset))
    ).scalars().all()
    return LabsPage(
        items=[LabItem(id=s.id, name=s.name, building=s.building) for s in salas],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/labs", response_model=LabItem, status_code=201)
async def crear_sala(
    body: LabCreate,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(obtener_base_datos),
) -> LabItem:
    existente = (
        await db.execute(select(Lab.id).where(Lab.name == body.name))
    ).scalar_one_or_none()
    if existente is not None:
        raise AppError(ErrorCode.CONFLICT, detail="Ya existe una sala con ese nombre.")
    sala = Lab(name=body.name, building=body.building)
    db.add(sala)
    try:
        await db.flush()
    except IntegrityError:
        # Carrera con otra petición que creó el mismo nombre entre el SELECT y el INSERT
        await db.rollback()
        raise AppError(ErrorCode.CONFLICT, detail="Ya existe una sala con ese nombre.")
    await audit(
        db,
        actor_type=AuditActorType.user,
        actor_id=admin.id,
        action="lab_created",
        target_type="lab",
        target_id=sala.id,
    )
    await db.commit()
    return LabItem(id=sala.id, name=sala.name, building=sala.building)


# ------------------------------------------------------------------------- equipos
@router.get("/machines", response_model=MachinesPage)
async def listar_equipos(
    lab_id: uuid.UUID | None = None,
    status: MachineStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(obtener_base_datos),
) -> MachinesPage:
    condiciones: list[Any] = []
    if lab_id is not None:
        condiciones.append(Machine.lab_id == lab_id)
    if status is not None:
        condiciones.append(Machine.status == status)
    total = (
        await db.execute(select(func.count()).select_from(Machine).where(*condiciones))
    ).scalar_one()
    filas = await db.execute(
        select(Machine, Lab.name)
        .outerjoin(Lab, Lab.id == Machine.lab_id)
        .where(*condiciones)
        .order_by(Machine.code)
        .limit(limit)
        .offset(offset)
    )
    return MachinesPage(
        items=[_item_equipo(m, lab) for m, lab in filas.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/machines/{machine_id}", response_model=MachineItem)
async def editar_equipo(
    machine_id: uuid.UUID,
    body: MachinePatch,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(obtener_base_datos),
) -> MachineItem:
    """Edita sala, modo o estado de un equipo.

    Deshabilitar un equipo (RN-08) cancela sus retos pendientes y cierra su sesión
    abierta con `admin_forced`. El equipo se bloquea primero con FOR UPDATE: respeta el
    orden de bloqueos de `services.challenges` (equipo -> retos -> sesiones).
    """
    machine = (
        await db.execute(
            select(Machine)
            .where(Machine.id == machine_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if machine is None:
        raise AppError(ErrorCode.NOT_FOUND, detail="El equipo no existe.")

    cambios = sorted(body.model_fields_set)
    if "lab_id" in body.model_fields_set and body.lab_id is not None:
        if (await db.execute(select(Lab.id).where(Lab.id == body.lab_id))).scalar_one_or_none() is None:
            raise AppError(ErrorCode.NOT_FOUND, detail="La sala no existe.")
    if "lab_id" in body.model_fields_set:
        machine.lab_id = body.lab_id
    if body.mode is not None:
        machine.mode = body.mode

    if body.status is not None:
        nuevo = MachineStatus(body.status)
        if nuevo == MachineStatus.active and machine.enrolled_at is None:
            raise AppError(
                ErrorCode.CONFLICT,
                detail="El equipo aún no se enroló; no se puede activar.",
            )
        if nuevo == MachineStatus.disabled and machine.status != MachineStatus.disabled:
            ahora = challenges.ahora()
            await db.execute(
                update(LoginChallenge)
                .where(
                    LoginChallenge.machine_id == machine.id,
                    LoginChallenge.status == ChallengeStatus.pending,
                )
                .values(status=ChallengeStatus.cancelled)
                .execution_options(synchronize_session=False)
            )
            cerrada = await sesiones.cerrar_sesion_de_equipo(
                db, machine.id, SessionEndReason.admin_forced, ahora
            )
            if cerrada is not None:
                await sesiones.auditar_cierre(
                    db,
                    actor_type=AuditActorType.user,
                    actor_id=admin.id,
                    session_id=cerrada,
                    motivo=SessionEndReason.admin_forced,
                )
        machine.status = nuevo

    await audit(
        db,
        actor_type=AuditActorType.user,
        actor_id=admin.id,
        action="machine_updated",
        target_type="machine",
        target_id=machine.id,
        metadata_info={"fields": cambios},
    )
    await db.flush()
    lab_name = None
    if machine.lab_id is not None:
        lab_name = (
            await db.execute(select(Lab.name).where(Lab.id == machine.lab_id))
        ).scalar_one_or_none()
    item = _item_equipo(machine, lab_name)
    await db.commit()
    return item


# ------------------------------------------------------------------------- sesiones
@router.get("/sessions", response_model=AdminSessionsPage)
async def consultar_sesiones(
    machine_code: str | None = Query(default=None, max_length=40),
    lab_id: uuid.UUID | None = None,
    state: Literal["active", "ended"] | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(obtener_base_datos),
) -> AdminSessionsPage:
    """Consulta de accesos con filtros y paginación estricta (limit ≤ 100)."""
    started_from, started_to = _utc(started_from), _utc(started_to)
    condiciones: list[Any] = []
    if machine_code is not None:
        condiciones.append(Machine.code == machine_code)
    if lab_id is not None:
        condiciones.append(Machine.lab_id == lab_id)
    if state == "active":
        condiciones.append(AccessSession.ended_at.is_(None))
    elif state == "ended":
        condiciones.append(AccessSession.ended_at.is_not(None))
    if started_from is not None:
        condiciones.append(AccessSession.started_at >= started_from)
    if started_to is not None:
        condiciones.append(AccessSession.started_at < started_to)

    total = (
        await db.execute(
            select(func.count())
            .select_from(AccessSession)
            .join(Machine, Machine.id == AccessSession.machine_id)
            .where(*condiciones)
        )
    ).scalar_one()
    filas = await db.execute(
        _consulta_sesiones(*condiciones)
        .order_by(AccessSession.started_at.desc(), AccessSession.id)
        .limit(limit)
        .offset(offset)
    )
    return AdminSessionsPage(
        items=[_item_sesion(s, u, codigo, lab) for s, u, codigo, lab in filas.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/sessions/{session_id}/end", response_model=AdminSessionResponse)
async def cerrar_sesion_forzada(
    session_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(obtener_base_datos),
) -> AdminSessionResponse:
    """Cierre forzado (`admin_forced`). Idempotente: si ya estaba cerrada la devuelve igual.

    El equipo se entera en su próximo latido (≤ 60 s).
    """
    motivo = SessionEndReason.admin_forced
    cerrada = await sesiones.cerrar_sesion_abierta(db, session_id, motivo, challenges.ahora())
    if cerrada:
        await sesiones.auditar_cierre(
            db,
            actor_type=AuditActorType.user,
            actor_id=admin.id,
            session_id=session_id,
            motivo=motivo,
        )
    fila = (await db.execute(_consulta_sesiones(AccessSession.id == session_id))).first()
    if fila is None:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, detail="La sesión no existe.")
    sesion, usuario, codigo, lab = fila
    item = _item_sesion(sesion, usuario, codigo, lab)
    await db.commit()
    return AdminSessionResponse(session=item)
