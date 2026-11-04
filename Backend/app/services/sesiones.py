"""Sesiones de acceso: latido, cierres y consultas (SRS §8.3, RN-01, RN-03, RN-07; BE-18).

Reglas que cumple este módulo:
- RN-01: toda marca de tiempo la fija el servidor; ninguna función acepta horas del cliente.
- Cada cierre es un único `UPDATE ... WHERE ended_at IS NULL ... RETURNING`: es atómico
  y no pisa un cierre anterior (el primero gana, el reintento es idempotente).
- Ninguna función devuelve ni registra tokens, credenciales ni códigos sin enmascarar.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.models import (
    AccessSession,
    AuditActorType,
    Lab,
    Machine,
    SessionEndReason,
    User,
)
from app.services.challenges import ahora, mask_student_code

LAB_SIN_ASIGNAR = "Sala sin asignar"
NOMBRE_POR_DEFECTO = "Estudiante"


def texto_plano(valor: bytes | None, por_defecto: str) -> str:
    """Texto de una columna *_ct.

    Hoy las columnas guardan los bytes en UTF-8 (igual que `challenges`). Cuando exista
    el TypeDecorator AES-256-GCM del SRS §12.7 solo cambia esta función.
    """
    if not valor:
        return por_defecto
    try:
        return valor.decode("utf-8", errors="ignore") or por_defecto
    except Exception:
        return por_defecto


def datos_estudiante(usuario: User | None) -> tuple[str, str]:
    """(nombre completo, código enmascarado). Nunca devuelve el código completo."""
    if usuario is None:
        return NOMBRE_POR_DEFECTO, mask_student_code(None)
    nombre = texto_plano(usuario.full_name_ct, NOMBRE_POR_DEFECTO)
    codigo = texto_plano(usuario.student_code_ct, "")
    return nombre, mask_student_code(codigo)


def duracion_s(inicio: datetime, fin: datetime | None) -> int | None:
    """Duración en segundos de una sesión cerrada; None si sigue abierta."""
    if fin is None:
        return None
    return max(0, int((fin - inicio).total_seconds()))


# --------------------------------------------------------------------------- cierres
async def cerrar_sesion_abierta(
    db: AsyncSession,
    session_id: uuid.UUID,
    motivo: SessionEndReason,
    now: datetime,
    *,
    user_id: uuid.UUID | None = None,
    machine_id: uuid.UUID | None = None,
) -> bool:
    """Cierra la sesión `session_id` si sigue abierta. True si esta llamada la cerró.

    `user_id` / `machine_id` restringen la propiedad en el propio WHERE: una sesión ajena
    se comporta igual que una inexistente (SESSION_NOT_FOUND), sin revelar que existe.
    """
    condiciones = [AccessSession.id == session_id, AccessSession.ended_at.is_(None)]
    if user_id is not None:
        condiciones.append(AccessSession.user_id == user_id)
    if machine_id is not None:
        condiciones.append(AccessSession.machine_id == machine_id)
    resultado = await db.execute(
        update(AccessSession)
        .where(*condiciones)
        .values(ended_at=now, end_reason=motivo)
        .returning(AccessSession.id)
        .execution_options(synchronize_session=False)
    )
    return resultado.first() is not None


async def cerrar_sesion_de_equipo(
    db: AsyncSession,
    machine_id: uuid.UUID,
    motivo: SessionEndReason,
    now: datetime,
) -> uuid.UUID | None:
    """Cierra la sesión abierta del equipo (hay a lo sumo una, RN-04). Devuelve su id."""
    resultado = await db.execute(
        update(AccessSession)
        .where(AccessSession.machine_id == machine_id, AccessSession.ended_at.is_(None))
        .values(ended_at=now, end_reason=motivo)
        .returning(AccessSession.id)
        .execution_options(synchronize_session=False)
    )
    fila = resultado.first()
    return fila[0] if fila else None


async def auditar_cierre(
    db: AsyncSession,
    *,
    actor_type: AuditActorType,
    actor_id: uuid.UUID | None,
    session_id: uuid.UUID,
    motivo: SessionEndReason,
) -> None:
    """Deja en audit_log quién cerró la sesión y por qué (sin PII)."""
    await audit(
        db=db,
        actor_type=actor_type,
        actor_id=actor_id,
        action="session_ended",
        target_type="access_session",
        target_id=session_id,
        metadata_info={"end_reason": motivo.value},
    )


async def cerrar_sesiones_inactivas(
    db: AsyncSession,
    now: datetime | None = None,
    timeout_s: int | None = None,
) -> int:
    """RN-07: cierra las sesiones sin latido en `timeout_s` con ended_at = last_heartbeat_at.

    Pensada para la tarea periódica (rol de jobs). No hace commit: lo hace quien la llama.
    """
    now = now or ahora()
    limite = now - timedelta(seconds=timeout_s or settings.heartbeat_timeout_s)
    resultado = await db.execute(
        update(AccessSession)
        .where(AccessSession.ended_at.is_(None), AccessSession.last_heartbeat_at <= limite)
        .values(
            ended_at=AccessSession.last_heartbeat_at,
            end_reason=SessionEndReason.heartbeat_timeout,
        )
        .returning(AccessSession.id)
        .execution_options(synchronize_session=False)
    )
    ids = [fila[0] for fila in resultado.all()]
    for session_id in ids:
        await auditar_cierre(
            db,
            actor_type=AuditActorType.system,
            actor_id=None,
            session_id=session_id,
            motivo=SessionEndReason.heartbeat_timeout,
        )
    return len(ids)


# --------------------------------------------------------------------------- latido
async def registrar_latido(
    db: AsyncSession,
    machine_id: uuid.UUID,
    now: datetime,
    session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Registra el latido del equipo y responde el estado de su sesión (SRS §8.3).

    - Con sesión abierta: actualiza `last_heartbeat_at` y responde `active` (con su id).
    - Sin sesión abierta y con `session_id` (la que el equipo cree tener): si esa sesión
      ya cerró, responde `ended` con el motivo, que es como el equipo se entera de un
      cierre remoto (web, administrador o reemplazo) en su próximo latido.
    - En cualquier otro caso responde `none`.
    El `session_id` solo se consulta dentro de las sesiones de ESTE equipo.
    """
    await db.execute(
        update(Machine)
        .where(Machine.id == machine_id)
        .values(last_seen_at=now)
        .execution_options(synchronize_session=False)
    )
    actualizada = (
        await db.execute(
            update(AccessSession)
            .where(AccessSession.machine_id == machine_id, AccessSession.ended_at.is_(None))
            .values(last_heartbeat_at=now)
            .returning(AccessSession.id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if actualizada is not None:
        return {"session_status": "active", "session_id": actualizada[0]}

    if session_id is not None:
        previa = (
            await db.execute(
                select(AccessSession.ended_at, AccessSession.end_reason).where(
                    AccessSession.id == session_id,
                    AccessSession.machine_id == machine_id,
                )
            )
        ).first()
        if previa is not None and previa.ended_at is not None:
            return {
                "session_status": "ended",
                "session_id": session_id,
                "end_reason": previa.end_reason,
            }
    return {"session_status": "none"}


# ------------------------------------------------------------------------ consultas
async def accesos_recientes(
    db: AsyncSession, user_id: uuid.UUID, limite: int = 5
) -> list[dict[str, Any]]:
    """Últimos accesos cerrados del estudiante (para la pantalla del equipo)."""
    filas = await db.execute(
        select(AccessSession, Machine.code, Lab.name)
        .join(Machine, Machine.id == AccessSession.machine_id)
        .outerjoin(Lab, Lab.id == Machine.lab_id)
        .where(AccessSession.user_id == user_id, AccessSession.ended_at.is_not(None))
        .order_by(AccessSession.ended_at.desc())
        .limit(limite)
    )
    return [
        {
            "machine_code": codigo,
            "lab": lab or LAB_SIN_ASIGNAR,
            "started_at": sesion.started_at,
            "ended_at": sesion.ended_at,
            "duration_s": duracion_s(sesion.started_at, sesion.ended_at),
        }
        for sesion, codigo, lab in filas.all()
    ]


async def obtener_sesion_actual(db: AsyncSession, machine_id: uuid.UUID) -> dict[str, Any] | None:
    """Sesión abierta del equipo con los datos mínimos del estudiante (SRS §12.6)."""
    sesion = (
        await db.execute(
            select(AccessSession)
            .where(AccessSession.machine_id == machine_id, AccessSession.ended_at.is_(None))
            .order_by(AccessSession.started_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if sesion is None:
        return None
    usuario = (
        await db.execute(select(User).where(User.id == sesion.user_id))
    ).scalar_one_or_none()
    nombre, codigo = datos_estudiante(usuario)
    return {
        "session": {"id": sesion.id, "status": "active", "started_at": sesion.started_at},
        "user": {"full_name": nombre, "student_code_masked": codigo},
        "recent_accesses": await accesos_recientes(db, sesion.user_id),
    }
