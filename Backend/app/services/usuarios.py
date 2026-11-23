"""Administración de cuentas por línea de comandos (BE-20, RN-12).

Dos operaciones que usa ``tools.admin_cli``:

- ``crear_admin``: crea el administrador inicial (no hay registro web de admins).
- ``bloquear_usuario``: deja la cuenta en ``blocked``, revoca todos sus refresh
  tokens (cierra sus sesiones web) y cierra su acceso activo en el PC con
  ``admin_forced``. El equipo se entera en su próximo latido (≤ 60 s).

Ninguna función hace commit: lo decide quien llama. Los datos personales se
guardan y buscan solo por la interfaz ``pii``, y nunca van a la auditoría.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.models import (
    AccessSession,
    AuditActorType,
    RefreshToken,
    SessionEndReason,
    User,
    UserRole,
    UserStatus,
)
from app.services import pii, sesiones
from app.services.passwords import hash_password, validate_password_policy

LARGO_MAXIMO_NOMBRE = 120


class UsuarioYaExiste(ValueError):
    """Ya hay una cuenta con ese correo."""


class UsuarioNoEncontrado(ValueError):
    """No hay ninguna cuenta con ese correo."""


@dataclass(frozen=True)
class ResultadoBloqueo:
    """Lo que hizo ``bloquear_usuario``.

    Attributes:
        user_id: Id de la cuenta bloqueada.
        ya_estaba_bloqueada: True si la cuenta ya estaba en ``blocked``.
        refresh_revocados: Cuántos refresh tokens vigentes se revocaron.
        sesion_cerrada: Id de la sesión de acceso que se cerró, si había una abierta.
    """

    user_id: uuid.UUID
    ya_estaba_bloqueada: bool
    refresh_revocados: int
    sesion_cerrada: uuid.UUID | None


def normalizar_correo(email: str) -> str:
    """Recorta y pasa a minúsculas un correo, igual que el índice ciego.

    Args:
        email: Correo tal como llega.

    Returns:
        El correo normalizado.

    Raises:
        ValueError: Si no parece un correo.
    """
    normalizado = email.strip().lower()
    local, _, dominio = normalizado.partition("@")
    if not local or "." not in dominio or " " in normalizado:
        raise ValueError("El correo no es válido.")
    return normalizado


async def buscar_por_correo(db: AsyncSession, email: str) -> User | None:
    """Busca una cuenta por el índice ciego de su correo.

    Args:
        db: Sesión de base de datos.
        email: Correo de la cuenta.

    Returns:
        La cuenta, o ``None`` si no existe.
    """
    return await db.scalar(select(User).where(User.email_bidx == pii.indice_ciego(email)))


async def crear_admin(db: AsyncSession, *, email: str, nombre: str, password: str) -> User:
    """Crea una cuenta de administrador activa.

    Args:
        db: Sesión de base de datos.
        email: Correo del administrador.
        nombre: Nombre completo.
        password: Contraseña; debe cumplir la política de 10 a 128 caracteres.

    Returns:
        La cuenta creada (ya con id).

    Raises:
        ValueError: Si el correo o el nombre no son válidos.
        PasswordPolicyError: Si la contraseña no cumple la política.
        UsuarioYaExiste: Si ya hay una cuenta con ese correo.
    """
    email = normalizar_correo(email)
    nombre = nombre.strip()
    if not nombre or len(nombre) > LARGO_MAXIMO_NOMBRE:
        raise ValueError(f"El nombre debe tener entre 1 y {LARGO_MAXIMO_NOMBRE} caracteres.")
    validate_password_policy(password)
    if await buscar_por_correo(db, email) is not None:
        raise UsuarioYaExiste("Ya existe una cuenta con ese correo.")

    ahora = datetime.now(UTC)
    admin = User(
        email_ct=pii.proteger(email),
        email_bidx=pii.indice_ciego(email),
        full_name_ct=pii.proteger(nombre),
        password_hash=hash_password(password),
        role=UserRole.admin,
        status=UserStatus.active,
        email_verified_at=ahora,
        privacy_consent_at=ahora,
    )
    db.add(admin)
    await db.flush()
    await audit(
        db,
        AuditActorType.system,
        "cli.create_admin",
        target_type="user",
        target_id=admin.id,
    )
    return admin


async def bloquear_usuario(db: AsyncSession, *, email: str) -> ResultadoBloqueo:
    """Bloquea una cuenta y corta todo su acceso (RN-12).

    Es idempotente: si la cuenta ya estaba bloqueada vuelve a revocar y cerrar lo
    que haya quedado abierto, sin error.

    Args:
        db: Sesión de base de datos.
        email: Correo de la cuenta.

    Returns:
        Qué se bloqueó, revocó y cerró.

    Raises:
        ValueError: Si el correo no es válido.
        UsuarioNoEncontrado: Si no hay una cuenta con ese correo.
    """
    usuario = await buscar_por_correo(db, normalizar_correo(email))
    if usuario is None:
        raise UsuarioNoEncontrado("No existe una cuenta con ese correo.")

    ahora = datetime.now(UTC)
    ya_bloqueada = usuario.status == UserStatus.blocked
    usuario.status = UserStatus.blocked

    revocados = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == usuario.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=ahora)
        .returning(RefreshToken.id)
        .execution_options(synchronize_session=False)
    )
    refresh_revocados = len(revocados.all())

    abierta = await db.scalar(
        select(AccessSession.id).where(
            AccessSession.user_id == usuario.id, AccessSession.ended_at.is_(None)
        )
    )
    sesion_cerrada = None
    motivo = SessionEndReason.admin_forced
    if abierta is not None and await sesiones.cerrar_sesion_abierta(
        db, abierta, motivo, ahora, user_id=usuario.id
    ):
        sesion_cerrada = abierta
        await sesiones.auditar_cierre(
            db,
            actor_type=AuditActorType.system,
            actor_id=None,
            session_id=abierta,
            motivo=motivo,
        )

    await audit(
        db,
        AuditActorType.system,
        "cli.block_user",
        target_type="user",
        target_id=usuario.id,
        metadata_info={
            "ya_estaba_bloqueada": ya_bloqueada,
            "refresh_revocados": refresh_revocados,
            "sesion_cerrada": sesion_cerrada is not None,
        },
    )
    await db.flush()
    return ResultadoBloqueo(usuario.id, ya_bloqueada, refresh_revocados, sesion_cerrada)
