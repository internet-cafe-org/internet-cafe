"""ST-BE-02 (HU-26): endpoints admin de usuarios sobre la API real y PostgreSQL.

- ``GET /admin/users``: listado paginado y búsqueda exacta por correo o código con el
  índice ciego; el código siempre sale enmascarado y una fila dañada no tumba el listado.
- ``PATCH /admin/users/{id}``: cambia rol y estado. Bloquear hace lo mismo que
  ``admin_cli block-user`` (revoca refresh, cierra la sesión con ``admin_forced`` y lo
  audita), también si la cuenta ya estaba bloqueada. Un admin no puede quitarse el rol,
  bloquearse ni dejarse pendiente.
- Solo los administradores llegan: un estudiante recibe 403 y sin token, 401.

Los tokens se firman con claves efímeras y los datos son ficticios.
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import (
    AccessSession,
    AuditLog,
    ChallengeStatus,
    LoginChallenge,
    RefreshToken,
    SessionEndReason,
    User,
    UserRole,
    UserStatus,
)
from app.services import pii
from app.services.refresh_tokens import hash_token

API = "/api/v1"
ID_INEXISTENTE = "00000000-0000-4000-8000-000000000099"
CORREO_ALUMNO = "alumno@test.invalid"
CODIGO_ALUMNO = "2024001001"


# --------------------------------------------------------------------- ayudantes


def _par_de_claves() -> tuple[str, str]:
    """Par ES256 efímero (privada, pública) en PEM."""
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    publica = (
        clave.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return privada, publica


def _aad(user_id: uuid.UUID, campo: str) -> str:
    """AAD con el que se cifra una columna de ``users``."""
    return f"users.{campo}.{user_id}"


def _crear_usuario(
    email: str,
    nombre: str,
    student_code: str | None = None,
    role: UserRole = UserRole.student,
    status: UserStatus = UserStatus.active,
) -> User:
    """Construye un usuario con los datos personales cifrados por ``pii``."""
    uid = uuid.uuid4()
    usuario = User(
        id=uid,
        email_ct=pii.proteger(email, aad=_aad(uid, "email_ct")),
        email_bidx=pii.indice_ciego(email),
        full_name_ct=pii.proteger(nombre, aad=_aad(uid, "full_name_ct")),
        password_hash="no-es-un-hash",
        role=role,
        status=status,
        privacy_consent_at=datetime.now(UTC),
    )
    if student_code is not None:
        usuario.student_code_ct = pii.proteger(student_code, aad=_aad(uid, "student_code_ct"))
        usuario.student_code_bidx = pii.indice_ciego(student_code)
    return usuario


def _cabecera(usuario: User) -> dict[str, str]:
    """Cabecera Authorization con un access token del usuario."""
    token = create_access_token(subject=str(usuario.id), role=usuario.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _refresh_vigente(sesiones: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> uuid.UUID:
    """Crea un refresh token vigente; el valor es aleatorio y no se guarda."""
    async with sesiones() as db:
        fila = RefreshToken(
            user_id=user_id,
            family_id=uuid.uuid4(),
            token_hash=hash_token(secrets.token_urlsafe(16)),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(fila)
        await db.commit()
        return fila.id


async def _sesion_abierta(sesiones: async_sessionmaker[AsyncSession], user_id: uuid.UUID, machine_id) -> uuid.UUID:
    """Crea un reto aprobado y la sesión de acceso abierta que sale de él."""
    ahora = datetime.now(UTC)
    async with sesiones() as db:
        reto = LoginChallenge(
            machine_id=machine_id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.approved,
            approved_by=user_id,
            approved_at=ahora,
            expires_at=ahora + timedelta(seconds=60),
        )
        db.add(reto)
        await db.flush()
        sesion = AccessSession(
            user_id=user_id,
            machine_id=machine_id,
            challenge_id=reto.id,
            started_at=ahora,
            last_heartbeat_at=ahora,
        )
        db.add(sesion)
        await db.commit()
        return sesion.id


async def _bloquear(cliente: AsyncClient, admin: User, usuario: User):
    """Bloquea la cuenta con ``PATCH /admin/users/{id}``."""
    return await cliente.patch(
        f"{API}/admin/users/{usuario.id}", json={"status": "blocked"}, headers=_cabecera(admin)
    )


# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def claves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claves ES256 efímeras para firmar y verificar los access tokens."""
    privada, publica = _par_de_claves()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)


@pytest.fixture
async def cliente(sesiones: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app con la base de prueba."""
    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Administrador activo."""
    usuario = _crear_usuario("admin@test.invalid", "Admin de Prueba", role=UserRole.admin)
    async with sesiones() as db:
        db.add(usuario)
        await db.commit()
    return usuario


@pytest.fixture
async def estudiante(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Estudiante activo con código."""
    usuario = _crear_usuario(CORREO_ALUMNO, "Alumno de Prueba", student_code=CODIGO_ALUMNO)
    async with sesiones() as db:
        db.add(usuario)
        await db.commit()
    return usuario


# --------------------------------------------------------------- GET /admin/users


async def test_listar_devuelve_la_pagina_del_contrato(cliente, admin, estudiante) -> None:
    resp = await cliente.get(f"{API}/admin/users", headers=_cabecera(admin))

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert (cuerpo["total"], cuerpo["limit"], cuerpo["offset"]) == (2, 20, 0)
    campos = {"id", "email", "full_name", "student_code_masked", "role", "status", "created_at"}
    assert all(set(item) == campos for item in cuerpo["items"])


async def test_paginacion_sin_repetir_ni_saltar_con_la_misma_fecha(cliente, sesiones, admin) -> None:
    """Con la misma ``created_at``, el id desempata y las páginas no se solapan."""
    misma_fecha = datetime(2026, 11, 1, tzinfo=UTC)
    async with sesiones() as db:
        for n in range(5):
            usuario = _crear_usuario(f"empate{n}@test.invalid", f"Empate {n}")
            usuario.created_at = misma_fecha
            db.add(usuario)
        await db.commit()

    vistos = []
    for offset in range(0, 6, 2):
        resp = await cliente.get(f"{API}/admin/users?limit=2&offset={offset}", headers=_cabecera(admin))
        vistos += [i["id"] for i in resp.json()["items"]]

    assert len(vistos) == len(set(vistos)) == 6


async def test_buscar_por_correo_exacto_normaliza_como_el_registro(cliente, admin, estudiante) -> None:
    resp = await cliente.get(
        f"{API}/admin/users", params={"email": "  Alumno@TEST.invalid "}, headers=_cabecera(admin)
    )

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["id"] == str(estudiante.id)
    assert cuerpo["items"][0]["email"] == CORREO_ALUMNO


async def test_buscar_por_codigo_exacto(cliente, admin, estudiante) -> None:
    resp = await cliente.get(f"{API}/admin/users", params={"student_code": CODIGO_ALUMNO}, headers=_cabecera(admin))

    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(estudiante.id)


async def test_buscar_correo_inexistente_devuelve_vacio(cliente, admin) -> None:
    resp = await cliente.get(f"{API}/admin/users", params={"email": "no@test.invalid"}, headers=_cabecera(admin))

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_respuesta_enmascara_el_codigo_y_no_expone_secretos(cliente, admin, estudiante) -> None:
    resp = await cliente.get(f"{API}/admin/users", params={"email": CORREO_ALUMNO}, headers=_cabecera(admin))

    item = resp.json()["items"][0]
    assert CODIGO_ALUMNO not in resp.text
    assert "*" in item["student_code_masked"]
    for prohibido in ("password_hash", "no-es-un-hash", "email_ct", "bidx"):
        assert prohibido not in resp.text


async def test_una_fila_que_no_se_descifra_no_tumba_el_listado(cliente, sesiones, admin, estudiante, caplog) -> None:
    """Un dato cifrado con otro AAD sale con valores por defecto; el log solo lleva el id."""
    async with sesiones() as db:
        fila = await db.get(User, estudiante.id)
        fila.email_ct = pii.proteger(CORREO_ALUMNO, aad="otro.aad")
        await db.commit()

    resp = await cliente.get(f"{API}/admin/users", headers=_cabecera(admin))

    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["id"] == str(estudiante.id))
    assert (item["email"], item["full_name"], item["student_code_masked"]) == ("", "Estudiante", "********")
    registro = next(r for r in caplog.records if r.getMessage().startswith("admin.users"))
    assert registro.datos == {"evento": "admin.users.pii_error", "user_id": str(estudiante.id)}
    assert CORREO_ALUMNO not in caplog.text


async def test_estudiante_recibe_403_y_sin_token_401(cliente, estudiante) -> None:
    assert (await cliente.get(f"{API}/admin/users", headers=_cabecera(estudiante))).status_code == 403
    assert (await cliente.get(f"{API}/admin/users")).status_code == 401


# --------------------------------------------------------- PATCH /admin/users/{id}


async def test_cambiar_rol_queda_auditado(cliente, sesiones, admin, estudiante) -> None:
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}", json={"role": "admin"}, headers=_cabecera(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    async with sesiones() as db:
        assert (await db.get(User, estudiante.id)).role == UserRole.admin
        registro = await db.scalar(select(AuditLog).where(AuditLog.action == "user_updated"))
    assert registro.actor_id == admin.id
    assert registro.target_id == estudiante.id
    assert registro.metadata_info == {"fields": ["role"]}


async def test_bloquear_revoca_refresh_y_cierra_la_sesion_auditada(cliente, sesiones, datos, admin, estudiante) -> None:
    """Igual que ``block-user``: revoca, cierra con ``admin_forced`` y audita ``session_ended``."""
    token_id = await _refresh_vigente(sesiones, estudiante.id)
    sesion_id = await _sesion_abierta(sesiones, estudiante.id, datos.pc01.id)

    resp = await _bloquear(cliente, admin, estudiante)

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"
    async with sesiones() as db:
        assert (await db.get(RefreshToken, token_id)).revoked_at is not None
        sesion = await db.get(AccessSession, sesion_id)
        cierre = await db.scalar(select(AuditLog).where(AuditLog.action == "session_ended"))
        cambio = await db.scalar(select(AuditLog).where(AuditLog.action == "user_updated"))
    assert sesion.ended_at is not None
    assert sesion.end_reason == SessionEndReason.admin_forced
    assert (cierre.actor_id, cierre.target_id) == (admin.id, sesion_id)
    assert cierre.metadata_info == {"end_reason": "admin_forced"}
    assert cambio.metadata_info == {"fields": ["status"], "refresh_revocados": 1, "sesion_cerrada": True}


async def test_bloquear_otra_vez_corta_lo_que_quedo_abierto(cliente, sesiones, datos, admin, estudiante) -> None:
    """Con la cuenta ya bloqueada, un refresh o una sesión que sigan vivos se cortan."""
    assert (await _bloquear(cliente, admin, estudiante)).status_code == 200
    token_id = await _refresh_vigente(sesiones, estudiante.id)
    sesion_id = await _sesion_abierta(sesiones, estudiante.id, datos.pc01.id)

    assert (await _bloquear(cliente, admin, estudiante)).status_code == 200

    async with sesiones() as db:
        assert (await db.get(RefreshToken, token_id)).revoked_at is not None
        assert (await db.get(AccessSession, sesion_id)).end_reason == SessionEndReason.admin_forced


async def test_desbloquear_devuelve_la_cuenta_a_activa(cliente, sesiones, admin, estudiante) -> None:
    assert (await _bloquear(cliente, admin, estudiante)).status_code == 200

    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}", json={"status": "active"}, headers=_cabecera(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    async with sesiones() as db:
        assert (await db.get(User, estudiante.id)).status == UserStatus.active


@pytest.mark.parametrize(
    "cuerpo",
    [{"status": "blocked"}, {"status": "pending_verification"}, {"role": "student"}],
    ids=["bloquearse", "dejarse-pendiente", "quitarse-el-rol"],
)
async def test_admin_no_puede_desactivarse_ni_quitarse_el_rol(cliente, sesiones, admin, cuerpo) -> None:
    resp = await cliente.patch(f"{API}/admin/users/{admin.id}", json=cuerpo, headers=_cabecera(admin))

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"
    async with sesiones() as db:
        propio = await db.get(User, admin.id)
    assert (propio.role, propio.status) == (UserRole.admin, UserStatus.active)


async def test_admin_puede_reafirmar_su_propio_rol_y_estado(cliente, admin) -> None:
    resp = await cliente.patch(
        f"{API}/admin/users/{admin.id}", json={"role": "admin", "status": "active"}, headers=_cabecera(admin)
    )

    assert resp.status_code == 200


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"role": None}, {"status": None}, {"role": "root"}, {"email": "x@test.invalid"}],
    ids=["vacio", "role-null", "status-null", "rol-invalido", "campo-extra"],
)
async def test_cuerpo_invalido_da_422_sin_cambios_ni_auditoria(cliente, sesiones, admin, estudiante, cuerpo) -> None:
    resp = await cliente.patch(f"{API}/admin/users/{estudiante.id}", json=cuerpo, headers=_cabecera(admin))

    assert resp.status_code == 422
    async with sesiones() as db:
        assert await db.scalar(select(AuditLog).where(AuditLog.action == "user_updated")) is None


async def test_usuario_inexistente_da_404(cliente, admin) -> None:
    resp = await cliente.patch(
        f"{API}/admin/users/{ID_INEXISTENTE}", json={"role": "admin"}, headers=_cabecera(admin)
    )

    assert resp.status_code == 404


async def test_estudiante_no_puede_editar_usuarios(cliente, estudiante, admin) -> None:
    resp = await cliente.patch(
        f"{API}/admin/users/{admin.id}", json={"role": "student"}, headers=_cabecera(estudiante)
    )

    assert resp.status_code == 403
