"""Pruebas de integración para la exportación CSV de accesos (ST-BE-03)."""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import (
    AccessSession,
    ChallengeStatus,
    LoginChallenge,
    Machine,
    SessionEndReason,
    User,
    UserRole,
)
from app.services import pii

API = "/api/v1"


# ------------------------------------------------------------------------- Fixtures

@pytest.fixture(autouse=True)
def configurar_llave_blind_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura una llave falsa para el blind index antes de cualquier prueba.

    Necesario porque las fixtures (como admin_user) usan pii.indice_ciego
    y en la CI no hay BLIND_INDEX_KEY definida.
    """
    monkeypatch.setattr(settings, "blind_index_key", "0" * 64)


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> str:
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
    async with sesiones() as db:
        admin = User(
            email_ct=b"admin@test.invalid",
            email_bidx=uuid.uuid4().bytes,
            full_name_ct=b"Admin Test",
            student_code_ct=pii.proteger("999"),
            student_code_bidx=pii.indice_ciego("999"),
            password_hash="no-es-un-hash",
            role=UserRole.admin,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(admin)
        await db.commit()
        return admin


def _bearer_admin(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(subject=str(usuario.id), role="admin", private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _crear_sesion(
    sesiones: async_sessionmaker[AsyncSession],
    usuario: User,
    equipo: Machine,
    *,
    hace_min: int,
) -> uuid.UUID:
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
            ended_at=inicio + timedelta(minutes=1),
            end_reason=SessionEndReason.user_logout_pc,
        )
        db.add(sesion)
        await db.commit()
        return sesion.id


# ------------------------------------------------------------------------- Pruebas

async def test_exportar_csv_camino_feliz(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    cabeceras = _bearer_admin(claves, admin_user)

    resp = await cliente.get(f"{API}/admin/sessions/export", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=\"accesos.csv\"" in resp.headers["content-disposition"]

    contenido_bytes = resp.content
    assert contenido_bytes.startswith(b'\xef\xbb\xbf'), "Falta el BOM de UTF-8"

    texto = contenido_bytes.decode("utf-8-sig")
    lector = csv.reader(io.StringIO(texto), delimiter=',')
    filas = list(lector)

    assert len(filas) == 2  # Cabecera + 1 fila
    assert filas[0] == ["Estudiante", "Código", "Equipo", "Sala", "Inicio", "Fin", "Duración (min)", "Motivo de cierre"]
    assert filas[1][0] == "Estudiante Prueba 1"
    assert filas[1][2] == "LAB-TEST-PC01"
    assert filas[1][7] == "user_logout_pc"


async def test_exportar_csv_inyeccion_formulas(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    admin_user: User,
) -> None:
    """Un nombre que empiece con '=' debe ser neutralizado."""

    # Creamos un usuario con nombre malicioso
    async with sesiones() as db:
        malicioso = User(
            email_ct=pii.proteger("hacker@test.invalid"),
            email_bidx=pii.indice_ciego("hacker@test.invalid"),
            full_name_ct=pii.proteger("=SUM(A1:A2)"),
            student_code_ct=pii.proteger("666"),
            student_code_bidx=pii.indice_ciego("666"),
            password_hash="no-es-un-hash",
            role=UserRole.student,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(malicioso)
        await db.commit()

    await _crear_sesion(sesiones, malicioso, datos.pc01, hace_min=10)
    cabeceras = _bearer_admin(claves, admin_user)

    resp = await cliente.get(f"{API}/admin/sessions/export", headers=cabeceras)
    texto = resp.content.decode("utf-8-sig")
    filas = list(csv.reader(io.StringIO(texto), delimiter=','))

    # El nombre debe tener la comilla simple al inicio
    assert filas[1][0] == "'=SUM(A1:A2)"


async def test_exportar_csv_no_admin_da_403(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    token = create_access_token(subject=str(datos.ana.id), role="student", private_key=claves)
    resp = await cliente.get(
        f"{API}/admin/sessions/export",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
