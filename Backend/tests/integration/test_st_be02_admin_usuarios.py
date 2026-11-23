"""Pruebas de integración para ST-BE-02: endpoints admin de usuarios (HU-26).

Cubre sobre la API real (/api/v1) y PostgreSQL:
- GET /admin/users: sin filtro devuelve todos; con email o student_code hace
  búsqueda exacta por blind index; paginación funciona.
- PATCH /admin/users/{id}: cambia role y status; al bloquear revoca refresh
  tokens y cierra la sesión de acceso activa; no se puede bloquear a sí mismo.
- Control de acceso: solo admins llegan; estudiantes reciben 403.
- Sin secretos: la respuesta nunca devuelve password_hash ni el código completo.

No hay credenciales reales: los tokens se firman con claves efímeras y los
datos de usuario son ficticios (no PII real).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.crypto import compute_blind_index
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import (
    AccessSession,
    RefreshToken,
    User,
    UserRole,
    UserStatus,
)
from app.services import pii
from app.services.refresh_tokens import hash_token

API = "/api/v1"
ID_INEXISTENTE = "00000000-0000-4000-8000-000000000099"


# --------------------------------------------------------------------- helpers


def _par_de_claves() -> tuple[str, str]:
    """Par ES256 efímero (privada, pública) en PEM."""
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    publica = (
        clave.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return privada, publica


def _aad(user_id: uuid.UUID, campo: str) -> str:
    return f"users.{campo}.{user_id}"


def _crear_usuario(
    email: str,
    nombre: str,
    student_code: str | None = None,
    role: UserRole = UserRole.student,
    status: UserStatus = UserStatus.active,
) -> User:
    """Construye un User con datos cifrados con pii.proteger."""
    uid = uuid.uuid4()
    u = User(
        id=uid,
        email_ct=pii.proteger(email, aad=_aad(uid, "email_ct")),
        email_bidx=compute_blind_index(email),
        full_name_ct=pii.proteger(nombre, aad=_aad(uid, "full_name_ct")),
        password_hash="no-es-un-hash",
        role=role,
        status=status,
        privacy_consent_at=datetime.now(UTC),
    )
    if student_code is not None:
        u.student_code_ct = pii.proteger(student_code, aad=_aad(uid, "student_code_ct"))
        u.student_code_bidx = compute_blind_index(student_code)
    return u


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> str:
    """Claves ES256 efímeras para la API; devuelve la privada con la que firma."""
    privada, publica = _par_de_claves()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    return privada


@pytest.fixture
async def cliente(
    sesiones: async_sessionmaker[AsyncSession], claves: str
) -> AsyncIterator[AsyncClient]:
    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Administrador activo con datos cifrados."""
    u = _crear_usuario("admin@test.invalid", "Admin de Prueba", role=UserRole.admin)
    async with sesiones() as db:
        db.add(u)
        await db.commit()
    return u


@pytest.fixture
async def estudiante(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Estudiante activo con código."""
    u = _crear_usuario(
        "alumno@test.invalid",
        "Alumno de Prueba",
        student_code="2024001001",
    )
    async with sesiones() as db:
        db.add(u)
        await db.commit()
    return u


def _cab_admin(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(subject=str(usuario.id), role=usuario.role.value)
    return {"Authorization": f"Bearer {token}"}


def _cab_estudiante(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(subject=str(usuario.id), role=usuario.role.value)
    return {"Authorization": f"Bearer {token}"}


# ============================================================== tests


async def test_listar_usuarios_devuelve_pagina(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """GET /admin/users sin filtro devuelve los usuarios con la estructura del contrato."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users", headers=cab)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert "items" in cuerpo
    assert "total" in cuerpo
    assert "limit" in cuerpo
    assert "offset" in cuerpo
    assert cuerpo["total"] >= 2
    campos = {"id", "email", "full_name", "student_code_masked", "role", "status", "created_at"}
    for item in cuerpo["items"]:
        assert campos <= set(item.keys()), f"Faltan campos en {item}"


async def test_listar_usuarios_paginacion(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """limit y offset funcionan correctamente."""
    cab = _cab_admin(claves, admin)
    r1 = await cliente.get(f"{API}/admin/users?limit=1&offset=0", headers=cab)
    r2 = await cliente.get(f"{API}/admin/users?limit=1&offset=1", headers=cab)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(r1.json()["items"]) == 1
    assert len(r2.json()["items"]) == 1
    assert r1.json()["items"][0]["id"] != r2.json()["items"][0]["id"]


async def test_buscar_por_email_exacto(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """email exacto devuelve solo ese usuario."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users?email=alumno@test.invalid", headers=cab)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["id"] == str(estudiante.id)
    assert cuerpo["items"][0]["email"] == "alumno@test.invalid"


async def test_buscar_por_email_inexistente_devuelve_vacio(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """Email que no existe devuelve lista vacía."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users?email=noexiste@test.invalid", headers=cab)

    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


async def test_buscar_por_student_code_exacto(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """student_code exacto devuelve solo ese usuario."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users?student_code=2024001001", headers=cab)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(estudiante.id)


async def test_codigo_estudiante_siempre_enmascarado(
    cliente: AsyncClient,
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """student_code_masked nunca revela el código completo."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users?email=alumno@test.invalid", headers=cab)

    assert resp.status_code == 200
    mascara = resp.json()["items"][0]["student_code_masked"]
    assert "2024001001" not in mascara
    assert "*" in mascara


async def test_respuesta_no_incluye_secretos(
    cliente: AsyncClient,
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """La respuesta nunca expone password_hash ni campos internos."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.get(f"{API}/admin/users", headers=cab)

    texto = resp.text
    assert "password_hash" not in texto
    assert "no-es-un-hash" not in texto
    assert "email_ct" not in texto
    assert "bidx" not in texto


async def test_estudiante_no_puede_listar_usuarios(
    cliente: AsyncClient,
    claves: str,
    estudiante: User,
) -> None:
    """Un estudiante recibe 403 en GET /admin/users."""
    cab = _cab_estudiante(claves, estudiante)
    resp = await cliente.get(f"{API}/admin/users", headers=cab)
    assert resp.status_code == 403


async def test_sin_token_devuelve_401(
    cliente: AsyncClient,
) -> None:
    """Sin token la ruta devuelve 401."""
    resp = await cliente.get(f"{API}/admin/users")
    assert resp.status_code == 401


async def test_editar_usuario_cambia_role(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """PATCH /admin/users/{id} cambia el rol del usuario."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}",
        json={"role": "admin"},
        headers=cab,
    )

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["role"] == "admin"
    assert cuerpo["id"] == str(estudiante.id)

    # Verificar en BD
    async with sesiones() as db:
        u = await db.get(User, estudiante.id)
    assert u is not None
    assert u.role == UserRole.admin


async def test_editar_usuario_cambia_status(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """PATCH /admin/users/{id} cambia el status del usuario."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}",
        json={"status": "blocked"},
        headers=cab,
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"


async def test_bloquear_revoca_refresh_tokens(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """Bloquear un usuario revoca todos sus refresh tokens activos."""
    # Crear un refresh token activo para el estudiante
    raw_token = "tok-ficticio-st-be02-revocacion"
    async with sesiones() as db:
        fila = RefreshToken(
            user_id=estudiante.id,
            family_id=uuid.uuid4(),
            token_hash=hash_token(raw_token),
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        db.add(fila)
        await db.commit()
        token_id = fila.id

    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}",
        json={"status": "blocked"},
        headers=cab,
    )
    assert resp.status_code == 200

    # Verificar que el token fue revocado
    async with sesiones() as db:
        fila = await db.get(RefreshToken, token_id)
    assert fila is not None
    assert fila.revoked_at is not None


async def test_bloquear_cierra_sesion_de_acceso(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
    estudiante: User,
    datos,
) -> None:
    """Bloquear un usuario cierra su sesión de acceso activa con admin_forced."""
    # Crear una sesión de acceso abierta para el estudiante
    async with sesiones() as db:
        sesion = AccessSession(
            user_id=estudiante.id,
            machine_id=datos.pc01.id,
            challenge_id=uuid.uuid4(),
            started_at=datetime.now(UTC),
            last_heartbeat_at=datetime.now(UTC),
        )
        db.add(sesion)
        await db.commit()
        sesion_id = sesion.id

    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}",
        json={"status": "blocked"},
        headers=cab,
    )
    assert resp.status_code == 200

    # Verificar que la sesión fue cerrada
    async with sesiones() as db:
        s = await db.get(AccessSession, sesion_id)
    assert s is not None
    assert s.ended_at is not None
    assert s.end_reason.value == "admin_forced"


async def test_no_bloquear_propio_admin(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """Un admin no puede bloquearse a sí mismo (409)."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{admin.id}",
        json={"status": "blocked"},
        headers=cab,
    )
    assert resp.status_code == 409


async def test_editar_usuario_inexistente_devuelve_404(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """Editar un usuario que no existe devuelve 404."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{ID_INEXISTENTE}",
        json={"role": "admin"},
        headers=cab,
    )
    assert resp.status_code == 404


async def test_editar_sin_campos_devuelve_422(
    cliente: AsyncClient,
    claves: str,
    admin: User,
    estudiante: User,
) -> None:
    """PATCH sin campos devuelve 422."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.patch(
        f"{API}/admin/users/{estudiante.id}",
        json={},
        headers=cab,
    )
    assert resp.status_code == 422


async def test_estudiante_no_puede_editar_usuarios(
    cliente: AsyncClient,
    claves: str,
    estudiante: User,
    admin: User,
) -> None:
    """Un estudiante recibe 403 al intentar editar usuarios."""
    cab = _cab_estudiante(claves, estudiante)
    resp = await cliente.patch(
        f"{API}/admin/users/{admin.id}",
        json={"role": "student"},
        headers=cab,
    )
    assert resp.status_code == 403
