"""Refresh tokens rotativos con detección de reutilización (SEC-03a y SEC-03b).

En la base solo se guarda el SHA-256 del token. Cada uso del refresh revoca el
token presentado y emite uno nuevo de la misma familia (``replaced_by``).

Si llega un token ya revocado:

- **dentro de la gracia** (``REFRESH_GRACIA_S``, 10 s desde que se rotó) y con
  la familia todavía viva, se acepta y se emite otro token de la familia: es el
  caso de dos pestañas que renuevan casi a la vez (SRS §12.2);
- **fuera de la gracia**, o si fue revocado por un logout, se asume robo y se
  revoca toda la familia.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import fijar_contexto_rls
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
    # RLS (ST-SEC-05): solo se emiten tokens del usuario ya autenticado
    await fijar_contexto_rls(db, user_id=user_id)
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


async def revocar_todas_menos(
    db: AsyncSession, user_id: uuid.UUID, token_actual: str | None
) -> None:
    """Revoca los refresh tokens vigentes del usuario, salvo los de la sesión actual.

    Lo usa el cambio de contraseña (SEC-02): las demás sesiones web se cierran y la
    que hizo el cambio sigue abierta. No hace commit.

    Args:
        db: Sesión de base de datos.
        user_id: Dueño de los tokens.
        token_actual: Refresh token de la sesión que hace el cambio, si lo trae.
    """
    familia_actual = None
    if token_actual:
        familia_actual = await db.scalar(
            select(RefreshToken.family_id).where(
                RefreshToken.token_hash == hash_token(token_actual),
                RefreshToken.user_id == user_id,
            )
        )
    condiciones = [RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)]
    if familia_actual is not None:
        condiciones.append(RefreshToken.family_id != familia_actual)
    await db.execute(update(RefreshToken).where(*condiciones).values(revoked_at=_ahora()))

async def rotar(
    db: AsyncSession, token: str, user_agent: str | None = None
) -> Rotacion:
    """Valida el refresh, lo revoca y emite uno nuevo de la misma familia."""
    # RLS (ST-SEC-05): quien presenta el token solo puede ver ese token...
    await fijar_contexto_rls(db, refresh_hash=hash_token(token))
    registro = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(token))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if registro is None:
        raise RefreshInvalido("desconocido")
    # ...y, ya identificado su dueño, la familia completa de ese usuario
    await fijar_contexto_rls(db, user_id=registro.user_id)

    if registro.revoked_at is not None:
        if await _en_gracia(db, registro):
            return await _emitir_en_gracia(db, registro, user_agent)
        # Token ya usado fuera de la gracia: posible robo. Se cierra toda la familia.
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


async def _en_gracia(db: AsyncSession, registro: RefreshToken) -> bool:
    """Indica si un token revocado todavía se acepta por la gracia de SEC-03b.

    Solo aplica a un token revocado **por rotación** (tiene ``replaced_by``)
    hace menos de ``REFRESH_GRACIA_S`` segundos, y mientras la familia tenga
    algún token vigente (un logout o un reuso ya la habrían cerrado).

    Args:
        db: Sesión de base de datos.
        registro: Token revocado que se presentó.

    Returns:
        ``True`` si se acepta.
    """
    if registro.replaced_by is None or registro.revoked_at is None:
        return False
    if _ahora() - registro.revoked_at > timedelta(seconds=settings.refresh_gracia_s):
        return False
    vigente = await db.scalar(
        select(RefreshToken.id).where(
            RefreshToken.family_id == registro.family_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > _ahora(),
        ).limit(1)
    )
    return vigente is not None


async def _emitir_en_gracia(
    db: AsyncSession, registro: RefreshToken, user_agent: str | None
) -> Rotacion:
    """Emite otro token de la familia para una pestaña que llegó dentro de la gracia.

    Args:
        db: Sesión de base de datos.
        registro: Token revocado hace menos de ``REFRESH_GRACIA_S``.
        user_agent: ``User-Agent`` de la petición.

    Returns:
        La rotación con el token nuevo.

    Raises:
        RefreshInvalido: Si el usuario ya no está activo.
    """
    usuario = await db.get(User, registro.user_id)
    if usuario is None or usuario.status != UserStatus.active:
        await revocar_familia(db, registro.family_id)
        await db.commit()
        raise RefreshInvalido("usuario inactivo")
    nuevo, _ = await _crear(db, registro.user_id, user_agent, registro.family_id)
    await db.commit()
    return Rotacion(user_id=usuario.id, role=usuario.role, token=nuevo)


async def revocar(db: AsyncSession, token: str) -> None:
    """Cierra la sesion: revoca la familia del token. Es idempotente."""
    await fijar_contexto_rls(db, refresh_hash=hash_token(token))
    registro = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if registro is not None:
        await fijar_contexto_rls(db, user_id=registro.user_id)
        await revocar_familia(db, registro.family_id)
        await db.commit()