import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
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
    User,
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


async def _bloquear_equipo(db: AsyncSession, machine_id: uuid.UUID) -> Machine:
    """SELECT ... FOR UPDATE del equipo: primer bloqueo de toda operación que cambie retos.

    ORDEN DE BLOQUEOS (obligatorio para evitar deadlocks, BE-05 / BE-07b):
        1. fila del equipo  ->  2. filas de reto  ->  3. filas de sesión.
    `crear_reto` y `reclamar_reto_qr` lo respetan; así las operaciones del mismo
    equipo se serializan en el paso 1 sin retener todavía ningún reto.
    `populate_existing` refresca el objeto si ya estaba cargado en la sesión
    (por ejemplo por la dependencia del router) con el estado visto bajo el bloqueo.
    """
    resultado = await db.execute(
        select(Machine)
        .where(Machine.id == machine_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return resultado.scalar_one()


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
    """Crea un reto QR para el equipo y devuelve (reto, token en claro).

    BE-05 (bug de rotación): la fila del equipo se bloquea con FOR UPDATE antes de
    mirar los retos. Mientras un claim del mismo equipo está en curso, la rotación
    espera; cuando continúa ve el estado ya confirmado (`approved`). Además, todas
    las cancelaciones y vencimientos son UPDATE con `status = 'pending'` en el WHERE:
    aun si el estado cambiara entre la lectura y la escritura, un reto `approved`
    nunca se pisa.
    """
    now = now or ahora()
    machine = await _bloquear_equipo(db, machine_id)
    if machine.status != MachineStatus.active:
        raise MachineNotActiveError

    await _cerrar_sesion_huerfana(db, machine.id, now)

    # Vencidos: pending -> expired (solo si siguen pending)
    await db.execute(
        update(LoginChallenge)
        .where(
            LoginChallenge.machine_id == machine.id,
            LoginChallenge.status == ChallengeStatus.pending,
            LoginChallenge.expires_at <= now,
        )
        .values(status=ChallengeStatus.expired)
        .execution_options(synchronize_session=False)
    )

    # Vigentes, del más nuevo al más viejo
    vigentes_ids = (
        await db.execute(
            select(LoginChallenge.id)
            .where(
                LoginChallenge.machine_id == machine.id,
                LoginChallenge.status == ChallengeStatus.pending,
                LoginChallenge.expires_at > now,
            )
            .order_by(LoginChallenge.created_at.desc())
        )
    ).scalars().all()

    # RN-06: con el reto nuevo debe haber como máximo MAX_ACTIVE_CHALLENGES vigentes
    excedentes = list(vigentes_ids)[MAX_ACTIVE_CHALLENGES - 1:]
    if excedentes:
        await db.execute(
            update(LoginChallenge)
            .where(
                LoginChallenge.id.in_(excedentes),
                LoginChallenge.status == ChallengeStatus.pending,  # nunca pisa approved
            )
            .values(status=ChallengeStatus.cancelled)
            .execution_options(synchronize_session=False)
        )

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

    machine_res = await db.execute(select(Machine).where(Machine.id == reto.machine_id))
    machine = machine_res.scalar_one()
    lab_name = "Sala sin asignar"
    if machine.lab_id:
        lab_res = await db.execute(select(Lab).where(Lab.id == machine.lab_id))
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
        "machine": {"code": machine.code, "lab": lab_name},
        "expires_at": reto.expires_at,
        "active_session": active_session_data,
    }


async def reclamar_reto_qr(
    db: AsyncSession,
    token: str,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> tuple[AccessSession, Machine, str, bool]:
    """Reclama un reto QR creando la sesión en una transacción atómica (SRS §8.1 / BE-07b).

    1. Lectura SIN bloqueo del reto por token_hash, solo para saber su equipo.
    2. SELECT ... FOR UPDATE del equipo (primer bloqueo, ver `_bloquear_equipo`).
    3. SELECT ... FOR UPDATE del reto (releído con el estado actual).
    4. Validar idempotencia: si ya fue aprobado por el mismo usuario, devuelve la sesión existente.
    5. Validar estado pending y vigencia: si expiró o fue usado por otro, lanza error.
    6. Validar que el equipo esté activo y no ocupado (MACHINE_BUSY).
    7. Cerrar sesión activa previa del usuario en otro equipo (superseded).
    8. Marcar reto como approved y cancelar los demás pendientes del equipo con UN solo
       UPDATE masivo (ya bajo el bloqueo del equipo).
    9. Insertar nueva AccessSession y registrar en AuditLog.
    10. Commit y despertar al equipo con events.notify().

    BE-07b (deadlock): antes cada claim bloqueaba su reto y después pedía el equipo,
    mientras el ganador intentaba cancelar el reto del otro, que seguía bloqueado.
    Un UPDATE masivo por sí solo no lo evita (necesita igualmente el bloqueo de la fila
    del otro reto); lo que lo elimina es el orden equipo -> reto: quien pierde espera en
    el equipo sin retener ningún reto, y al entrar ve su reto ya `cancelled`
    (ChallengeAlreadyUsedError) o el equipo ocupado (MachineBusyError).
    """
    now = now or ahora()
    token_bytes = hash_token(token)

    # 1. Lectura sin bloqueo: solo para conocer el equipo
    reto = (
        await db.execute(
            select(LoginChallenge).where(LoginChallenge.token_hash == token_bytes)
        )
    ).scalar_one_or_none()
    if not reto:
        raise ChallengeNotFoundError

    # 2. Equipo primero: serializa los claims y las rotaciones del mismo equipo
    machine = await _bloquear_equipo(db, reto.machine_id)

    # 3. Reto bajo bloqueo, refrescado (puede haber cambiado mientras esperábamos)
    reto = (
        await db.execute(
            select(LoginChallenge)
            .where(LoginChallenge.token_hash == token_bytes)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not reto:
        raise ChallengeNotFoundError

    # 4. Idempotencia: si ya fue aprobado por el mismo estudiante, devolver la misma sesión
    if reto.status == ChallengeStatus.approved:
        if reto.approved_by == user_id:
            sesion_res = await db.execute(
                select(AccessSession).where(AccessSession.challenge_id == reto.id)
            )
            sesion = sesion_res.scalar_one_or_none()
            if sesion:
                lab_name = "Sala sin asignar"
                if machine.lab_id:
                    lab_res = await db.execute(select(Lab).where(Lab.id == machine.lab_id))
                    lab = lab_res.scalar_one_or_none()
                    if lab:
                        lab_name = lab.name
                return sesion, machine, lab_name, True
        raise ChallengeAlreadyUsedError
    if reto.status != ChallengeStatus.pending:
        raise ChallengeAlreadyUsedError

    # 5. Validar vigencia
    if reto.expires_at <= now:
        reto.status = ChallengeStatus.expired
        await db.flush()
        raise ChallengeExpiredError

    # 6. Estado del equipo y MACHINE_BUSY (RF-SES-03 / RN-08)
    if machine.status != MachineStatus.active:
        raise MachineNotActiveError
    sesion_equipo_res = await db.execute(
        select(AccessSession).where(
            AccessSession.machine_id == machine.id, AccessSession.ended_at.is_(None)
        )
    )
    if sesion_equipo_res.first():
        raise MachineBusyError

    # 7. Cerrar sesión activa previa del usuario en otro equipo (superseded, RF-SES-04)
    sesiones_usuario_res = await db.execute(
        select(AccessSession).where(
            AccessSession.user_id == user_id,
            AccessSession.ended_at.is_(None),
            AccessSession.machine_id != machine.id,
        )
    )
    for sesion_previa in sesiones_usuario_res.scalars().all():
        close_session(sesion_previa, SessionEndReason.superseded, now)

    # 8. Aprobar este reto y cancelar los demás pendientes del equipo (RN-06) con un
    #    UPDATE masivo. El WHERE status = 'pending' impide tocar retos ya resueltos.
    reto.status = ChallengeStatus.approved
    reto.approved_by = user_id
    reto.approved_at = now
    await db.execute(
        update(LoginChallenge)
        .where(
            LoginChallenge.machine_id == machine.id,
            LoginChallenge.status == ChallengeStatus.pending,
            LoginChallenge.id != reto.id,
        )
        .values(status=ChallengeStatus.cancelled)
        .execution_options(synchronize_session=False)
    )

    # 9. Insertar la nueva AccessSession (SRS §8.1.5)
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

    # Registrar en el log de auditoría (SRS §8.1.6); sin PII ni tokens
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

    # 10. Obtener datos de sala, usuario y notificar al equipo (SRS §8.1.7)
    lab_name = "Sala sin asignar"
    if machine.lab_id:
        lab_res = await db.execute(select(Lab).where(Lab.id == machine.lab_id))
        lab = lab_res.scalar_one_or_none()
        if lab:
            lab_name = lab.name

    full_name = "Estudiante"
    student_code_masked = "********"
    user_res = await db.execute(select(User).where(User.id == user_id))
    user_obj = user_res.scalar_one_or_none()
    if user_obj:
        if user_obj.full_name_ct:
            try:
                full_name = user_obj.full_name_ct.decode("utf-8", errors="ignore") or "Estudiante"
            except Exception:
                full_name = "Estudiante"
        if user_obj.student_code_ct:
            try:
                raw_code = user_obj.student_code_ct.decode("utf-8", errors="ignore")
                student_code_masked = mask_student_code(raw_code)
            except Exception:
                pass

    session_payload = {
        "status": "approved",
        "session": {
            "id": nueva_sesion.id,
            "status": "active",
            "started_at": nueva_sesion.started_at,
        },
        "user": {
            "full_name": full_name,
            "student_code_masked": student_code_masked,
        },
        "recent_accesses": [],
    }
    events.notify(machine.id, session_payload)
    return nueva_sesion, machine, lab_name, False


def mask_student_code(code: str | None) -> str:
    """Enmascara el código de estudiante para proteger PII (SRS §9.1 / RNF-PRI-02).

    Ejemplo: '20211020034' -> '2021****34'
    """
    if not code:
        return "********"
    if len(code) <= 4:
        return "****"
    if len(code) <= 6:
        return f"{code[:2]}**{code[-2:]}"
    return f"{code[:4]}{'*' * (len(code) - 6)}{code[-2:]}"


async def obtener_sesion_activa_equipo(
    db: AsyncSession,
    machine_id: uuid.UUID,
) -> dict | None:
    """Busca si el equipo tiene una sesión activa y retorna los datos estructurados para long-poll (SRS §8.1)."""
    stmt = (
        select(AccessSession)
        .where(
            AccessSession.machine_id == machine_id,
            AccessSession.ended_at.is_(None),
        )
        .order_by(AccessSession.started_at.desc())
    )
    res = await db.execute(stmt)
    sesion = res.scalar_one_or_none()
    if not sesion:
        return None

    full_name = "Estudiante"
    student_code_masked = "********"
    if sesion.user_id:
        user_res = await db.execute(select(User).where(User.id == sesion.user_id))
        user_obj = user_res.scalar_one_or_none()
        if user_obj:
            if user_obj.full_name_ct:
                try:
                    full_name = user_obj.full_name_ct.decode("utf-8", errors="ignore") or "Estudiante"
                except Exception:
                    full_name = "Estudiante"
            if user_obj.student_code_ct:
                try:
                    raw_code = user_obj.student_code_ct.decode("utf-8", errors="ignore")
                    student_code_masked = mask_student_code(raw_code)
                except Exception:
                    pass

    return {
        "status": "approved",
        "session": {
            "id": sesion.id,
            "status": "active",
            "started_at": sesion.started_at,
        },
        "user": {
            "full_name": full_name,
            "student_code_masked": student_code_masked,
        },
        "recent_accesses": [],
    }
