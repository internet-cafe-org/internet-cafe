import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.models import (
    AccessSession,
    AuditActorType,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineStatus,
    SessionEndReason,
)
from app.services import events

CHALLENGE_TTL_S = 60
ROTATE_AFTER_S = 45
MAX_ACTIVE_CHALLENGES = 2


class MachineNotActiveError(Exception):
    """El equipo no está en estado active (RN-08)."""


class ChallengeNotFoundError(Exception):
    """El reto no existe o el hash no coincide."""


class ChallengeExpiredError(Exception):
    """El reto ha expirado."""


class ChallengeAlreadyUsedError(Exception):
    """El reto ya no está pendiente."""


class MachineBusyError(Exception):
    """El equipo ya tiene una sesión activa (RF-SES-03)."""


def ahora() -> datetime:
    """Hora actual del servidor en UTC."""
    return datetime.now(timezone.utc)


def generar_token() -> str:
    """Token de 256 bits, apto para URL."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """SHA-256 del token: en la base solo se guarda el hash."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def close_session(sesion: AccessSession, motivo: SessionEndReason, now: datetime) -> None:
    """Cierra una sesión de acceso con la hora del servidor."""
    sesion.ended_at = now
    sesion.end_reason = motivo


async def _cerrar_sesion_huerfana(db: AsyncSession, machine_id, now: datetime) -> None:
    """RN-02: cierra la sesión abierta del equipo (superseded)."""
    filas = await db.execute(
        select(AccessSession, LoginChallenge)
        .join(LoginChallenge, LoginChallenge.id == AccessSession.challenge_id)
        .where(AccessSession.machine_id == machine_id, AccessSession.ended_at.is_(None))
    )
    for sesion, reto in filas.all():
        if reto.expires_at <= now:
            close_session(sesion, SessionEndReason.superseded, now)


async def crear_reto(
    db: AsyncSession, machine_id, now: datetime | None = None
) -> tuple[LoginChallenge, str]:
    """Crea un reto QR para el equipo y devuelve (reto, token en claro)."""
    now = now or ahora()

    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one()
    if machine.status != MachineStatus.active:
        raise MachineNotActiveError

    await _cerrar_sesion_huerfana(db, machine.id, now)

    pendientes = (
        await db.execute(
            select(LoginChallenge)
            .where(
                LoginChallenge.machine_id == machine.id,
                LoginChallenge.status == ChallengeStatus.pending,
            )
            .order_by(LoginChallenge.created_at.desc())
        )
    ).scalars().all()

    vigentes = []
    for reto in pendientes:
        if reto.expires_at <= now:
            reto.status = ChallengeStatus.expired
        else:
            vigentes.append(reto)

    for viejo in vigentes[MAX_ACTIVE_CHALLENGES - 1:]:
        viejo.status = ChallengeStatus.cancelled

    token = generar_token()
    nuevo = LoginChallenge(
        machine_id=machine.id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(seconds=CHALLENGE_TTL_S),
        created_at=now,
    )
    db.add(nuevo)
    await db.flush()
    return nuevo, token


async def obtener_vista_previa(db: AsyncSession, token: str, user_id) -> dict:
    """Obtiene los datos de previsualización de un reto QR sin consumirlo."""
    token_bytes = hash_token(token)

    reto_res = await db.execute(
        select(LoginChallenge).where(LoginChallenge.token_hash == token_bytes)
    )
    reto = reto_res.scalar_one_or_none()

    if not reto:
        raise ChallengeNotFoundError

    if reto.status != ChallengeStatus.pending:
        raise ChallengeAlreadyUsedError

    if reto.expires_at <= ahora():
        reto.status = ChallengeStatus.expired
        await db.flush()
        raise ChallengeExpiredError

    machine_res = await db.execute(
        select(Machine).where(Machine.id == reto.machine_id)
    )
    machine = machine_res.scalar_one()

    lab_name = "Sala sin asignar"
    if machine.lab_id:
        lab_res = await db.execute(
            select(Lab).where(Lab.id == machine.lab_id)
        )
        lab = lab_res.scalar_one_or_none()
        if lab:
            lab_name = lab.name

    sesion_activa_res = await db.execute(
        select(AccessSession, Machine)
        .join(Machine, Machine.id == AccessSession.machine_id)
        .where(AccessSession.user_id == user_id, AccessSession.ended_at.is_(None))
    )
    fila_sesion = sesion_activa_res.first()

    active_session_data = None
    if fila_sesion:
        sesion_activa, machine_activa = fila_sesion
        active_session_data = {"machine_code": machine_activa.code}

    return {
        "machine": {
            "code": machine.code,
            "lab": lab_name
        },
        "expires_at": reto.expires_at,
        "active_session": active_session_data
    }


async def reclamar_reto_qr(
    db: AsyncSession,
    token: str,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> tuple[AccessSession, Machine, str, bool]:
    """Reclama un reto QR creando la sesión en una transacción atómica (SRS §8.1 / BE-07b).

    1. SELECT ... FOR UPDATE del reto por token_hash.
    2. Validar idempotencia: si ya fue aprobado por el mismo usuario, devuelve la sesión existente.
    3. Validar estado pending y vigencia: si expiró o fue usado por otro, lanza error.
    4. Validar que el equipo esté activo y no ocupado (MACHINE_BUSY).
    5. Cerrar sesión activa previa del usuario en otro equipo (superseded).
    6. Marcar reto como approved y cancelar otros retos pendientes del equipo.
    7. Insertar nueva AccessSession y registrar en AuditLog.
    8. Commit y despertar al equipo con events.notify().
    """
    now = now or ahora()
    token_bytes = hash_token(token)

    # 1. SELECT ... FOR UPDATE del reto para serializar reclamaciones simultáneas (SRS §8.1.1)
    stmt = (
        select(LoginChallenge)
        .where(LoginChallenge.token_hash == token_bytes)
        .with_for_update()
    )
    reto_res = await db.execute(stmt)
    reto = reto_res.scalar_one_or_none()

    if not reto:
        raise ChallengeNotFoundError

    # 2. Idempotencia: si ya fue aprobado por el mismo estudiante, devolver la misma sesión (SRS §8.1.2)
    if reto.status == ChallengeStatus.approved:
        if reto.approved_by == user_id:
            sesion_res = await db.execute(
                select(AccessSession).where(AccessSession.challenge_id == reto.id)
            )
            sesion = sesion_res.scalar_one_or_none()
            if sesion:
                machine_res = await db.execute(
                    select(Machine).where(Machine.id == reto.machine_id)
                )
                machine = machine_res.scalar_one()
                lab_name = "Sala sin asignar"
                if machine.lab_id:
                    lab_res = await db.execute(
                        select(Lab).where(Lab.id == machine.lab_id)
                    )
                    lab = lab_res.scalar_one_or_none()
                    if lab:
                        lab_name = lab.name
                return sesion, machine, lab_name, True
        raise ChallengeAlreadyUsedError

    if reto.status != ChallengeStatus.pending:
        raise ChallengeAlreadyUsedError

    # 3. Validar vigencia
    if reto.expires_at <= now:
        reto.status = ChallengeStatus.expired
        await db.flush()
        raise ChallengeExpiredError

    # 4. Validar estado del equipo y MACHINE_BUSY (RF-SES-03 / RN-08)
    machine_res = await db.execute(
        select(Machine).where(Machine.id == reto.machine_id).with_for_update()
    )
    machine = machine_res.scalar_one()
    if machine.status != MachineStatus.active:
        raise MachineNotActiveError

    # Comprobar si el equipo ya tiene una sesión activa
    sesion_equipo_res = await db.execute(
        select(AccessSession)
        .where(AccessSession.machine_id == machine.id, AccessSession.ended_at.is_(None))
    )
    if sesion_equipo_res.first():
        raise MachineBusyError

    # 5. Cerrar sesión activa previa del usuario en otro equipo (superseded, SRS §8.1.3 / RF-SES-04)
    sesiones_usuario_res = await db.execute(
        select(AccessSession)
        .where(
            AccessSession.user_id == user_id,
            AccessSession.ended_at.is_(None),
            AccessSession.machine_id != machine.id,
        )
    )
    for sesion_previa in sesiones_usuario_res.scalars().all():
        close_session(sesion_previa, SessionEndReason.superseded, now)

    # 6. Marcar reto como approved y cancelar retos residuales del equipo (SRS §8.1.4)
    reto.status = ChallengeStatus.approved
    reto.approved_by = user_id
    reto.approved_at = now

    otros_retos_res = await db.execute(
        select(LoginChallenge)
        .where(
            LoginChallenge.machine_id == machine.id,
            LoginChallenge.status == ChallengeStatus.pending,
            LoginChallenge.id != reto.id,
        )
    )
    for otro in otros_retos_res.scalars().all():
        otro.status = ChallengeStatus.cancelled

    # 7. Insertar la nueva AccessSession (SRS §8.1.5)
    nueva_sesion = AccessSession(
        user_id=user_id,
        machine_id=machine.id,
        challenge_id=reto.id,
        started_at=now,
        last_heartbeat_at=now,
        ended_at=None,
        end_reason=None,
    )
    db.add(nueva_sesion)
    await db.flush()

    # 8. Registrar en el log de auditoría (SRS §8.1.6)
    await audit(
        db=db,
        actor_type=AuditActorType.user,
        actor_id=user_id,
        action="session_claimed",
        target_type="access_session",
        target_id=nueva_sesion.id,
        metadata_info={
            "machine_code": machine.code,
            "challenge_id": str(reto.id),
            "session_id": str(nueva_sesion.id),
        },
    )

    # Confirmar transacción en BD
    await db.commit()

    # 9. Obtener nombre de la sala y notificar al equipo (SRS §8.1.7)
    lab_name = "Sala sin asignar"
    if machine.lab_id:
        lab_res = await db.execute(select(Lab).where(Lab.id == machine.lab_id))
        lab = lab_res.scalar_one_or_none()
        if lab:
            lab_name = lab.name

    session_payload = {
        "status": "approved",
        "session": {
            "id": str(nueva_sesion.id),
            "status": "active",
            "started_at": nueva_sesion.started_at.isoformat(),
            "machine": {
                "id": str(machine.id),
                "code": machine.code,
                "lab": lab_name,
            },
        },
    }
    events.notify(machine.id, session_payload)

    return nueva_sesion, machine, lab_name, False
