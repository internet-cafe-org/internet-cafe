import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccessSession,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineStatus,
    SessionEndReason,
)

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
