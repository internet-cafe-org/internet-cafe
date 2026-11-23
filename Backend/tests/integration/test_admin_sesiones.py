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
from httpx import ASGITransport, AsyncClient, Response
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
    UserStatus,
)
from app.services import pii

API = "/api/v1"


# ------------------------------------------------------------------------- Fixtures


@pytest.fixture(autouse=True)
def configurar_llave_blind_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura una llave falsa para el blind index antes de cualquier prueba.

    Necesario porque las fixtures usan pii.indice_ciego y en la CI no hay
    BLIND_INDEX_KEY definida.
    """
    monkeypatch.setattr(settings, "blind_index_key", "0" * 64)


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
async def cliente(sesiones: async_sessionmaker[AsyncSession], claves: str) -> AsyncIterator[AsyncClient]:
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
            email_ct=pii.proteger("admin@test.invalid"),
            email_bidx=pii.indice_ciego("admin@test.invalid"),
            full_name_ct=pii.proteger("Admin Test"),
            student_code_ct=pii.proteger("999"),
            student_code_bidx=pii.indice_ciego("999"),
            password_hash="no-es-un-hash",
            role=UserRole.admin,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(admin)
        await db.commit()
        return admin


# -------------------------------------------------------------------------- Helpers


def _bearer_admin(claves: str, usuario: User) -> dict[str, str]:
    """Genera el token JWT de administrador."""
    token = create_access_token(subject=str(usuario.id), role="admin", private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _crear_estudiante(
    sesiones: async_sessionmaker[AsyncSession],
    *,
    correo: str,
    nombre: str,
    codigo: str,
) -> User:
    """Crea un estudiante con sus datos protegidos y su blind index real.

    A diferencia de los de la fixture `datos`, este estudiante sí se puede
    encontrar con el filtro `student` (correo o código exacto).
    """
    async with sesiones() as db:
        estudiante = User(
            email_ct=pii.proteger(correo),
            email_bidx=pii.indice_ciego(correo),
            full_name_ct=pii.proteger(nombre),
            student_code_ct=pii.proteger(codigo),
            student_code_bidx=pii.indice_ciego(codigo),
            password_hash="no-es-un-hash",
            role=UserRole.student,
            status=UserStatus.active,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(estudiante)
        await db.commit()
        return estudiante


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


def _ids(resp: Response) -> list[str]:
    """Ids de las sesiones que devolvió el listado."""
    return [item["id"] for item in resp.json()["items"]]


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
    resp = await cliente.get(f"{API}/admin/sessions?machine_code={datos.pc01.code}", headers=cabeceras)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == str(abierta_pc01)

    # 5. Filtrar por sala (lab_id)
    resp = await cliente.get(f"{API}/admin/sessions?lab_id={datos.lab.id}", headers=cabeceras)
    assert resp.json()["total"] == 2  # Ambas sesiones están en la misma sala


async def test_admin_filtra_por_estudiante_correo(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Filtro por estudiante (correo): exacto, ignora mayúsculas y no trae a otros."""
    ana = await _crear_estudiante(
        sesiones,
        correo="ana.test@universidad.edu.co",
        nombre="Ana Test",
        codigo="111",
    )
    # Dos sesiones de estudiantes distintos: sin el filtro el total sería 2
    sesion_ana = await _crear_sesion(sesiones, ana, datos.pc01, hace_min=10)
    sesion_beto = await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    # Buscamos con mayúsculas para comprobar que el correo se normaliza
    resp = await cliente.get(f"{API}/admin/sessions?student=ANA.TEST@UNIVERSIDAD.EDU.CO", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert _ids(resp) == [str(sesion_ana)]
    assert str(sesion_beto) not in _ids(resp)
    assert resp.json()["items"][0]["user"]["full_name"] == "Ana Test"


async def test_admin_filtra_por_estudiante_codigo(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Filtro por estudiante (código): exacto, recorta espacios y no trae a otros."""
    beto = await _crear_estudiante(
        sesiones,
        correo="beto.test@universidad.edu.co",
        nombre="Beto Test",
        codigo="222",
    )
    # Dos sesiones de estudiantes distintos: sin el filtro el total sería 2
    sesion_ana = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    sesion_beto = await _crear_sesion(sesiones, beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    # Buscamos con espacios alrededor para comprobar que el código se normaliza
    resp = await cliente.get(f"{API}/admin/sessions?student= 222 ", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert _ids(resp) == [str(sesion_beto)]
    assert str(sesion_ana) not in _ids(resp)
    assert resp.json()["items"][0]["user"]["full_name"] == "Beto Test"


async def test_admin_filtra_por_estudiante_correo_inexistente(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Caso negativo: un correo que no existe da total == 0."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    resp = await cliente.get(f"{API}/admin/sessions?student=no-existe@test.invalid", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


async def test_admin_filtra_por_estudiante_codigo_inexistente(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Caso negativo: un código que no existe da total == 0."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)
    cabeceras = _bearer_admin(claves, admin_user)

    resp = await cliente.get(f"{API}/admin/sessions?student=777777", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


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
    ayer = (ahora - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    manana = (ahora + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fechas (formato estricto ISO 8601 con Z)
    resp = await cliente.get(
        f"{API}/admin/sessions?started_from={ayer}&started_to={manana}", headers=cabeceras
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    # Paginación
    resp = await cliente.get(f"{API}/admin/sessions?limit=1&offset=0", headers=cabeceras)
    assert resp.status_code == 200
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


async def test_estudiante_no_puede_acceder_al_admin(cliente: AsyncClient, claves: str, datos: Any) -> None:
    token = create_access_token(subject=str(datos.ana.id), role="student", private_key=claves)
    cabeceras = {"Authorization": f"Bearer {token}"}

    resp = await cliente.get(f"{API}/admin/sessions", headers=cabeceras)

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
