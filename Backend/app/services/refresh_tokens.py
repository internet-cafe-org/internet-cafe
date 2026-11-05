"""Refresh tokens rotativos con deteccion de reutilizacion (SEC-03a).

En la base solo se guarda el SHA-256 del token. Cada uso del refresh revoca el
token presentado y emite uno nuevo de la misma familia (replaced_by). Si llega
un token ya revocado se asume robo y se revoca toda la familia.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RefreshToken, User, UserRole, UserStatus


class RefreshInvalido(Exception):
    """Token inexistente, revocado, reutilizado o de un usuario inactivo."""


class RefreshExpirado(Exception):
    """Token vencido."""


@dataclass(frozen=True)
class Rotacion:
    """Resultado de una rotacion exitosa."""

    user_id: uuid.UUID
    role: UserRole
    token: str


def generar_token() -> str:
    """Token opaco de 256 bits, apto para cookie."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """SHA-256 del token: en la base solo se guarda el hash."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def _ahora() -> datetime:
    return datetime.now(UTC)


async def _crear(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_agent: str | None,
    family_id: uuid.UUID | None,
) -> tuple[str, RefreshToken]:
    token = generar_token()
    fila = RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(token),
        expires_at=_ahora() + timedelta(days=settings.refresh_token_expire_days),
        user_agent=user_agent[:255] if user_agent else None,
    )
    db.add(fila)
    await db.flush()
    return token, fila


async def emitir(
    db: AsyncSession, user_id: uuid.UUID, user_agent: str | None = None
) -> str:
    """Crea un refresh token en una familia nueva (lo usa el login).

    No hace commit: quien lo llama confirma la transaccion.
    """
    token, _ = await _crear(db, user_id, user_agent, None)
    return token


async def revocar_familia(db: AsyncSession, family_id: uuid.UUID) -> None:
    """Revoca todos los tokens vigentes de una familia."""
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_ahora())
    )


async def rotar(
    db: AsyncSession, token: str, user_agent: str | None = None
) -> Rotacion:
    """Valida el refresh, lo revoca y emite uno nuevo de la misma familia."""
    registro = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(token))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if registro is None:
        raise RefreshInvalido("desconocido")

    if registro.revoked_at is not None:
        # Token ya usado: posible robo. Se cierra toda la familia.
        await revocar_familia(db, registro.family_id)
        await db.commit()
        raise RefreshInvalido("reutilizado")

    if registro.expires_at <= _ahora():
        raise RefreshExpirado()

    usuario = await db.get(User, registro.user_id)
    if usuario is None or usuario.status != UserStatus.active:
        await revocar_familia(db, registro.family_id)
        await db.commit()
        raise RefreshInvalido("usuario inactivo")

    nuevo, fila_nueva = await _crear(db, registro.user_id, user_agent, registro.family_id)
    registro.revoked_at = _ahora()
    registro.replaced_by = fila_nueva.id
    await db.commit()
    return Rotacion(user_id=usuario.id, role=usuario.role, token=nuevo)


async def revocar(db: AsyncSession, token: str) -> None:
    """Cierra la sesion: revoca la familia del token. Es idempotente."""
    registro = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if registro is not None:
        await revocar_familia(db, registro.family_id)
        await db.commit()