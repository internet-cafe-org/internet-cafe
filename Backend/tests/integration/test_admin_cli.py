"""CLI create-admin y block-user contra PostgreSQL real (BE-20, RN-12)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models import (
    AccessSession,
    AuditLog,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineStatus,
    RefreshToken,
    SessionEndReason,
    User,
    UserRole,
    UserStatus,
)
from app.services import pii, refresh_tokens
from app.services.passwords import PasswordPolicyError, verify_password
from app.services.usuarios import (
    UsuarioNoEncontrado,
    UsuarioYaExiste,
    bloquear_usuario,
    crear_admin,
)

CORREO_ADMIN = "admin@test.invalid"
CORREO_ESTUDIANTE = "estudiante@test.invalid"  # ficticio


@pytest.fixture(autouse=True)
def clave_indice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clave ficticia del índice ciego, solo para estas pruebas."""
    monkeypatch.setattr(settings, "blind_index_key", "1" * 64)


async def _estudiante(sesiones: async_sessionmaker) -> User:
    async with sesiones() as db:
        usuario = User(
            email_ct=pii.proteger(CORREO_ESTUDIANTE),
            email_bidx=pii.indice_ciego(CORREO_ESTUDIANTE),
            full_name_ct=pii.proteger("Estudiante Prueba"),
            password_hash="no-es-un-hash",
            role=UserRole.student,
            status=UserStatus.active,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(usuario)
        await db.commit()
    return usuario


async def _acceso_abierto(sesiones: async_sessionmaker, usuario: User) -> uuid.UUID:
    inicio = datetime.now(UTC) - timedelta(minutes=5)
    async with sesiones() as db:
        lab = Lab(name="Sala CLI")
        db.add(lab)
        await db.flush()
        equipo = Machine(code="CLI-PC01", lab_id=lab.id, status=MachineStatus.active)
        db.add(equipo)
        await db.flush()
        reto = LoginChallenge(
            machine_id=equipo.id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.approved,
            approved_by=usuario.id,
            approved_at=inicio,
            expires_at=inicio + timedelta(seconds=60),
        )
        db.add(reto)
        await db.flush()
        sesion = AccessSession(
            user_id=usuario.id,
            machine_id=equipo.id,
            challenge_id=reto.id,
            started_at=inicio,
            last_heartbeat_at=inicio,
        )
        db.add(sesion)
        await db.commit()
    return sesion.id


async def test_create_admin_crea_cuenta_activa(sesiones: async_sessionmaker) -> None:
    async with sesiones() as db:
        admin = await crear_admin(
            db, email="  Admin@Test.Invalid ", nombre="Admin Prueba", password="contrasena-larga"
        )
        await db.commit()

    async with sesiones() as db:
        guardado = await db.scalar(
            select(User).where(User.email_bidx == pii.indice_ciego(CORREO_ADMIN))
        )
        accion = await db.scalar(select(AuditLog).where(AuditLog.target_id == admin.id))
    assert guardado.id == admin.id
    assert (guardado.role, guardado.status) == (UserRole.admin, UserStatus.active)
    assert pii.revelar(guardado.email_ct) == CORREO_ADMIN
    assert verify_password("contrasena-larga", guardado.password_hash)
    assert accion.action == "cli.create_admin"
    assert accion.metadata_info is None  # la auditoría no lleva el correo


async def test_create_admin_rechaza_correo_repetido(sesiones: async_sessionmaker) -> None:
    async with sesiones() as db:
        await crear_admin(db, email=CORREO_ADMIN, nombre="Uno", password="contrasena-larga")
        await db.commit()
    async with sesiones() as db:
        with pytest.raises(UsuarioYaExiste):
            await crear_admin(db, email=CORREO_ADMIN, nombre="Dos", password="contrasena-larga")


@pytest.mark.parametrize(
    ("email", "nombre", "password", "error"),
    [
        (CORREO_ADMIN, "Admin", "corta", PasswordPolicyError),
        ("sin-arroba", "Admin", "contrasena-larga", ValueError),
        (CORREO_ADMIN, "   ", "contrasena-larga", ValueError),
    ],
)
async def test_create_admin_valida_los_datos(
    sesiones: async_sessionmaker, email: str, nombre: str, password: str, error: type
) -> None:
    async with sesiones() as db:
        with pytest.raises(error):
            await crear_admin(db, email=email, nombre=nombre, password=password)


async def test_block_user_revoca_web_y_cierra_el_acceso(sesiones: async_sessionmaker) -> None:
    usuario = await _estudiante(sesiones)
    async with sesiones() as db:
        token_vivo = await refresh_tokens.emitir(db, usuario.id)
        await refresh_tokens.emitir(db, usuario.id)  # otra pestaña u otro navegador
        await db.commit()
    sesion_id = await _acceso_abierto(sesiones, usuario)

    async with sesiones() as db:
        resultado = await bloquear_usuario(db, email=CORREO_ESTUDIANTE.upper())
        await db.commit()

    assert resultado.user_id == usuario.id
    assert not resultado.ya_estaba_bloqueada
    assert resultado.refresh_revocados == 2
    assert resultado.sesion_cerrada == sesion_id
    async with sesiones() as db:
        bloqueado = await db.get(User, usuario.id)
        vigentes = (
            await db.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == usuario.id, RefreshToken.revoked_at.is_(None)
                )
            )
        ).all()
        sesion = await db.get(AccessSession, sesion_id)
        acciones = set((await db.scalars(select(AuditLog.action))).all())
    assert bloqueado.status == UserStatus.blocked
    assert vigentes == []
    assert sesion.ended_at is not None
    assert sesion.end_reason == SessionEndReason.admin_forced
    assert {"cli.block_user", "session_ended"} <= acciones

    # El refresh revocado ya no sirve para renovar la sesión web.
    async with sesiones() as db:
        with pytest.raises(refresh_tokens.RefreshInvalido):
            await refresh_tokens.rotar(db, token_vivo)


async def test_block_user_es_idempotente(sesiones: async_sessionmaker) -> None:
    await _estudiante(sesiones)
    async with sesiones() as db:
        await bloquear_usuario(db, email=CORREO_ESTUDIANTE)
        await db.commit()
    async with sesiones() as db:
        resultado = await bloquear_usuario(db, email=CORREO_ESTUDIANTE)
        await db.commit()

    assert resultado.ya_estaba_bloqueada
    assert (resultado.refresh_revocados, resultado.sesion_cerrada) == (0, None)


async def test_block_user_de_cuenta_inexistente(sesiones: async_sessionmaker) -> None:
    async with sesiones() as db:
        with pytest.raises(UsuarioNoEncontrado):
            await bloquear_usuario(db, email="nadie@test.invalid")
