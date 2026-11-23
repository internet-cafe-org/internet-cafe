"""Pruebas de integración de cifrado PII con AAD por fila (SEC-06, parte 2)."""
import json
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.crypto import compute_blind_index
from app.database import obtener_base_datos
from app.main import app
from app.models import AccessSession, ChallengeStatus, LoginChallenge, User
from app.services import challenges, pii
from tests.integration.conftest import Datos
from tools.seed_dev import ADMIN_NOMBRE, sembrar


@pytest.fixture(autouse=True)
def _llaves_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "blind_index_key", secrets.token_hex(32))
    monkeypatch.setattr(
        settings, "data_enc_keys", json.dumps({"1": secrets.token_hex(32)})
    )
    monkeypatch.setattr(settings, "allowed_email_domains", "")
    monkeypatch.setattr(settings, "require_email_verification", False)


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura llaves ES256 efímeras para emitir y validar JWT."""
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


@pytest.fixture
async def cliente(
    sesiones: async_sessionmaker, claves: None
) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app con la base de datos de pruebas inyectada."""

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def test_registro_perfil_y_long_poll_cifran_y_revelan_con_aad(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos: Datos
) -> None:
    resp = await cliente.post(
        "/api/v1/auth/register",
        json={
            "email": "cifrado.aad@test.invalid",
            "student_code": "2026998877",
            "full_name": "Lucía Méndez",
            "password": "PasswordSegura#2026",
            "privacy_consent": True,
        },
    )
    assert resp.status_code == 202
    async with sesiones() as db:
        u = await db.scalar(
            select(User).where(User.email_bidx == pii.indice_ciego("cifrado.aad@test.invalid"))
        )
        assert u is not None and u.email_ct.startswith(b"v") and u.full_name_ct.startswith(b"v")
        assert u.student_code_ct.startswith(b"v")
        assert pii.revelar(u.email_ct, aad=f"users.email_ct.{u.id}") == "cifrado.aad@test.invalid"
        assert pii.revelar(u.student_code_ct, aad=f"users.student_code_ct.{u.id}") == "2026998877"
        assert pii.revelar(u.full_name_ct, aad=f"users.full_name_ct.{u.id}") == "Lucía Méndez"

    login = await cliente.post(
        "/api/v1/auth/login",
        json={"email": "cifrado.aad@test.invalid", "password": "PasswordSegura#2026"},
    )
    assert login.status_code == 200 and login.json()["user"]["full_name"] == "Lucía Méndez"

    me = await cliente.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200 and me.json()["email"] == "cifrado.aad@test.invalid"
    assert me.json()["full_name"] == "Lucía Méndez"

    async with sesiones() as db:
        now = datetime.now(UTC)
        reto = LoginChallenge(
            machine_id=datos.pc01.id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.approved,
            approved_by=u.id,
            approved_at=now,
            expires_at=now + timedelta(seconds=60),
        )
        db.add(reto)
        await db.flush()
        sesion = AccessSession(
            user_id=u.id,
            machine_id=datos.pc01.id,
            challenge_id=reto.id,
            started_at=now,
            last_heartbeat_at=now,
            ended_at=None,
        )
        db.add(sesion)
        await db.commit()
        activa = await challenges.obtener_sesion_activa_equipo(db, datos.pc01.id)
        assert activa is not None and activa["user"]["full_name"] == "Lucía Méndez"


async def test_mover_ciphertext_a_otra_fila_falla_por_aad(
    cliente: AsyncClient, sesiones: async_sessionmaker
) -> None:
    for correo, codigo in (
        ("victima.aad@test.invalid", "2026111111"),
        ("atacante.aad@test.invalid", "2026222222"),
    ):
        r = await cliente.post(
            "/api/v1/auth/register",
            json={
                "email": correo,
                "student_code": codigo,
                "full_name": "Usuario Prueba",
                "password": "PasswordSegura#2026",
                "privacy_consent": True,
            },
        )
        assert r.status_code == 202

    async with sesiones() as db:
        v = await db.scalar(
            select(User).where(User.email_bidx == pii.indice_ciego("victima.aad@test.invalid"))
        )
        a = await db.scalar(
            select(User).where(User.email_bidx == pii.indice_ciego("atacante.aad@test.invalid"))
        )
        assert v is not None and a is not None
        with pytest.raises(pii.PiiError):
            pii.revelar(v.email_ct, aad=f"users.email_ct.{a.id}")


async def test_sembrar_cifra_datos_del_admin_con_aad(sesiones: async_sessionmaker) -> None:
    kb = "clave-bidx-de-prueba-sec06"
    async with sesiones() as db:
        res = await sembrar(
            db,
            salas=1,
            equipos_por_sala=1,
            codigos=0,
            admin_email="admin.seed@test.invalid",
            admin_password="AdminPassword#2026",
            blind_index_key=kb,
        )
        await db.commit()
        assert res.admin_creado is True
        admin = await db.scalar(
            select(User).where(User.email_bidx == compute_blind_index("admin.seed@test.invalid", kb))
        )
        assert admin is not None and admin.email_ct.startswith(b"v")
        assert admin.full_name_ct.startswith(b"v")
        assert pii.revelar(admin.email_ct, aad=f"users.email_ct.{admin.id}") == "admin.seed@test.invalid"
        assert pii.revelar(admin.full_name_ct, aad=f"users.full_name_ct.{admin.id}") == ADMIN_NOMBRE
