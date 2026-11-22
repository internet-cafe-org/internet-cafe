"""Pruebas de integración para la consulta y el cierre forzado de accesos (BE-14).

Cubre HU-15 sobre la API real:
- GET /admin/sessions con filtros (estudiante, equipo, estado, fechas) y paginación.
- POST /admin/sessions/{id}/end (cierre forzado por admin) y su auditoría.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
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
    Machine,
    SessionEndReason,
    User,
    UserRole,
)

API = "/api/v1"


# ------------------------------------------------------------------------- Fixtures

@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> str:
    """Claves ES256 efímeras para la API; devuelve la privada con la que firma."""
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
async def admin_user(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Crea un usuario administrador para probar los endpoints."""
    async with sesiones() as db:
        admin = User(
            email_ct=b"admin@test.invalid",
            email_bidx=uuid.uuid4().bytes,
            full_name_ct=b"Admin Test",
            student_code_ct=b"999",
            student_code_bidx=uuid.uuid4().bytes,
            password_hash="no-es-un-hash",
            role=UserRole.admin,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(admin)
        await db.commit()
        return admin


def _bearer_admin(claves: str, usuario: User) -> dict[str, str]:
    """Genera el token JWT de administrador."""
    token = create_access_token(subject=str(usuario.id), role="admin", private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _crear_sesion(
    sesiones: async_sessionmaker[AsyncSession],
    usuario: User,
    equipo: Machine,
    *,
    hace_min: int,
    abierta: bool = False,
) -> uuid.UUID:
    """Inserta un reto aprobado y la sesión que origina."""
    inicio = datetime.now(UTC) - timedelta(minutes=hace_min)
    async with sesiones() as db:
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
            ended_at=None if abierta else inicio + timedelta(minutes=1),
            end_reason=None if abierta else SessionEndReason.user_logout_pc,
        )
        db.add(sesion)
        await db.commit()
        return sesion.id


async def _auditorias_de(sesiones: async_sessionmaker[AsyncSession], sesion_id: uuid.UUID) -> int:
    async with sesiones() as db:
        return (
            await db.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.target_id == sesion_id)
            )
        ).scalar_one()


# ------------------------------------------------------------------- GET /admin/sessions

async def test_admin_lista_sesiones_con_filtros(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    # Creamos dos sesiones: una abierta en PC01 y una cerrada en PC02
    abierta_pc01 = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10, abierta=True)
    cerrada_pc02 = await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    # 1. Listar todas
    resp = await cliente.get(f"{API}/admin/sessions", headers=cabeceras)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    # 2. Filtrar por estado activo
    resp = await cliente.get(f"{API}/admin/sessions?state=active", headers=cabeceras)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(abierta_pc01)

    # 3. Filtrar por estado terminado
    resp = await cliente.get(f"{API}/admin/sessions?state=ended", headers=cabeceras)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(cerrada_pc02)

    # 4. Filtrar por equipo
    resp = await cliente.get(
        f"{API}/admin/sessions?machine_code={datos.pc01.code}", headers=cabeceras
    )
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(abierta_pc01)


async def test_admin_filtra_por_estudiante_correo(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Filtro por estudiante (correo). Debe ser exacto e ignorar mayúsculas."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    # Buscamos por el correo real de Ana (con mayúsculas para probar la normalización)
    resp = await cliente.get(f"{API}/admin/sessions?student=ESTUDIANTE1@TEST.INVALID", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["user"]["full_name"] == "Estudiante Prueba 1"


async def test_admin_filtra_por_estudiante_codigo(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Filtro por estudiante (código). Debe ser exacto y aceptar espacios."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    cabeceras = _bearer_admin(claves, admin_user)

    # Buscamos por el código de Ana (con espacios al final para probar la normalización)
    resp = await cliente.get(f"{API}/admin/sessions?student= 0000000001 ", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["user"]["full_name"] == "Estudiante Prueba 1"


async def test_admin_filtra_por_fechas_y_paginacion(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    ahora = datetime.now(UTC)
    ayer = ahora - timedelta(days=1)
    manana = ahora + timedelta(days=1)

    # Fechas
    resp = await cliente.get(f"{API}/admin/sessions?started_from={ayer.isoformat()}&started_to={manana.isoformat()}", headers=cabeceras)
    assert resp.json()["total"] == 2

    # Paginación
    resp = await cliente.get(f"{API}/admin/sessions?limit=1&offset=0", headers=cabeceras)
    assert len(resp.json()["items"]) == 1
    assert resp.json()["total"] == 2


# ------------------------------------------------------- POST /admin/sessions/{id}/end

async def test_admin_cierra_sesion_forzada_y_audita(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    cabeceras = _bearer_admin(claves, admin_user)

    resp = await cliente.post(f"{API}/admin/sessions/{abierta}/end", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["session"]["end_reason"] == "admin_forced"

    async with sesiones() as db:
        guardada = await db.get(AccessSession, abierta)
        assert guardada.ended_at is not None
        assert guardada.end_reason == SessionEndReason.admin_forced

    assert await _auditorias_de(sesiones, abierta) == 1


async def test_admin_cierre_forzado_es_idempotente(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    cabeceras = _bearer_admin(claves, admin_user)

    primera = await cliente.post(f"{API}/admin/sessions/{abierta}/end", headers=cabeceras)
    segunda = await cliente.post(f"{API}/admin/sessions/{abierta}/end", headers=cabeceras)

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert await _auditorias_de(sesiones, abierta) == 1


async def test_admin_cierre_forzado_sesion_inexistente(
    cliente: AsyncClient, claves: str, admin_user: User
) -> None:
    cabeceras = _bearer_admin(claves, admin_user)
    resp = await cliente.post(f"{API}/admin/sessions/{uuid.uuid4()}/end", headers=cabeceras)

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"


async def test_estudiante_no_puede_acceder_al_admin(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    token = create_access_token(subject=str(datos.ana.id), role="student", private_key=claves)
    cabeceras = {"Authorization": f"Bearer {token}"}

    resp = await cliente.get(f"{API}/admin/sessions", headers=cabeceras)

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
