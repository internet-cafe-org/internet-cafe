"""QA-07a: pruebas de /me, del cierre web y del acceso a recursos de otro estudiante.

Cubre HU-13 sobre la API real (/api/v1) y PostgreSQL:
- perfil con el código enmascarado (RF-EST-03);
- historial paginado de 20 en 20 y solo con sesiones propias (RF-EST-02);
- sesión activa (RF-EST-01);
- cierre desde la web con `user_logout_web` y auditoría (RF-SES-06, RF-ADM-09);
- IDOR entre estudiantes (SRS §12.1 T-10 y §12.6): una sesión ajena responde igual
  que una inexistente;
- "Cerrar sesión web" (RF-AUT-08) no termina el acceso al equipo.

La paginación sigue el contrato v0.2 (`limit`/`offset`, máximo 100), que es lo que
implementa la API. Las fixtures `claves` y `cliente` repiten las de
test_auth_negativas.py para no modificar ese archivo.
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
    UserStatus,
)
from app.routers.auth import COOKIE_NAME
from app.services import refresh_tokens

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


def _bearer(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(subject=str(usuario.id), role="student", private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _crear_sesion(
    sesiones: async_sessionmaker[AsyncSession],
    usuario: User,
    equipo: Machine,
    *,
    hace_min: int,
    abierta: bool = False,
) -> uuid.UUID:
    """Inserta un reto aprobado y la sesión que origina, empezada hace `hace_min` minutos."""
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


async def _sesion(
    sesiones: async_sessionmaker[AsyncSession], sesion_id: uuid.UUID
) -> AccessSession:
    async with sesiones() as db:
        return (
            await db.execute(select(AccessSession).where(AccessSession.id == sesion_id))
        ).scalar_one()


async def _auditorias_de(sesiones: async_sessionmaker[AsyncSession], sesion_id: uuid.UUID) -> int:
    async with sesiones() as db:
        return (
            await db.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.target_id == sesion_id)
            )
        ).scalar_one()


def _sin_instance(resp: Response) -> dict[str, Any]:
    """Cuerpo del error sin `instance`, que cambia con la URL pedida."""
    cuerpo: dict[str, Any] = resp.json()
    cuerpo.pop("instance", None)
    return cuerpo


# --------------------------------------------------------------------------- Perfil


async def test_perfil_devuelve_el_codigo_enmascarado(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    resp = await cliente.get(f"{API}/me", headers=_bearer(claves, datos.ana))

    assert resp.status_code == 200
    perfil = resp.json()
    assert perfil["id"] == str(datos.ana.id)
    assert perfil["full_name"] == "Estudiante Prueba 1"
    assert perfil["student_code_masked"] == "0000****01"
    assert "0000000001" not in resp.text  # el código completo nunca sale
    assert "password_hash" not in perfil


async def test_perfil_de_cuenta_bloqueada_responde_forbidden(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    async with sesiones() as db:
        ana = await db.get(User, datos.ana.id)
        assert ana is not None
        ana.status = UserStatus.blocked
        await db.commit()

    resp = await cliente.get(f"{API}/me", headers=_bearer(claves, datos.ana))

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


# ------------------------------------------------------------------------ Historial


async def test_historial_pagina_de_20_en_20_de_la_mas_reciente_a_la_mas_antigua(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    for minutos in range(25, 0, -1):
        await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=minutos * 10)
    cabeceras = _bearer(claves, datos.ana)

    primera = (await cliente.get(f"{API}/me/sessions", headers=cabeceras)).json()
    segunda = (await cliente.get(f"{API}/me/sessions?offset=20", headers=cabeceras)).json()

    assert (primera["total"], primera["limit"], len(primera["items"])) == (25, 20, 20)
    assert len(segunda["items"]) == 5
    inicios = [item["started_at"] for item in primera["items"] + segunda["items"]]
    assert inicios == sorted(inicios, reverse=True)
    item = primera["items"][0]
    assert item["machine_code"] == "LAB-TEST-PC01"
    assert item["lab"] == "Sala de pruebas"
    assert item["duration_s"] == 60


@pytest.mark.parametrize("consulta", ["limit=0", "limit=101", "offset=-1"])
async def test_historial_rechaza_paginacion_fuera_de_rango(
    cliente: AsyncClient, claves: str, datos: Any, consulta: str
) -> None:
    resp = await cliente.get(f"{API}/me/sessions?{consulta}", headers=_bearer(claves, datos.ana))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------- Sesión activa


async def test_sesion_activa_es_null_sin_sesion_abierta(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=30)

    resp = await cliente.get(f"{API}/me/sessions/active", headers=_bearer(claves, datos.ana))

    assert resp.status_code == 200
    assert resp.json() == {"session": None}


async def test_sesion_activa_devuelve_la_abierta(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)

    resp = await cliente.get(f"{API}/me/sessions/active", headers=_bearer(claves, datos.ana))

    sesion = resp.json()["session"]
    assert sesion["id"] == str(abierta)
    assert sesion["ended_at"] is None
    assert sesion["duration_s"] is None


# ---------------------------------------------------------------------- Cierre web


async def test_cierre_web_cierra_con_user_logout_web_y_audita(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)

    resp = await cliente.post(
        f"{API}/me/sessions/{abierta}/end", headers=_bearer(claves, datos.ana)
    )

    assert resp.status_code == 200
    assert resp.json()["session"]["end_reason"] == "user_logout_web"
    guardada = await _sesion(sesiones, abierta)
    assert guardada.ended_at is not None
    assert guardada.end_reason == SessionEndReason.user_logout_web
    assert await _auditorias_de(sesiones, abierta) == 1


async def test_cierre_web_es_idempotente(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    cabeceras = _bearer(claves, datos.ana)

    primera = await cliente.post(f"{API}/me/sessions/{abierta}/end", headers=cabeceras)
    segunda = await cliente.post(f"{API}/me/sessions/{abierta}/end", headers=cabeceras)

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json()["session"]["ended_at"] == primera.json()["session"]["ended_at"]
    assert await _auditorias_de(sesiones, abierta) == 1


async def test_cierre_web_de_sesion_inexistente(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    resp = await cliente.post(
        f"{API}/me/sessions/{uuid.uuid4()}/end", headers=_bearer(claves, datos.ana)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------- IDOR entre estudiantes (T-10)


async def test_historial_no_incluye_sesiones_de_otro_estudiante(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    propia = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=20)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=5, abierta=True)
    cabeceras = _bearer(claves, datos.ana)

    historial = (await cliente.get(f"{API}/me/sessions", headers=cabeceras)).json()
    activa = (await cliente.get(f"{API}/me/sessions/active", headers=cabeceras)).json()

    assert historial["total"] == 1
    assert [item["id"] for item in historial["items"]] == [str(propia)]
    assert activa == {"session": None}


async def test_no_se_puede_cerrar_la_sesion_de_otro_estudiante(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    de_beto = await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=5, abierta=True)

    resp = await cliente.post(
        f"{API}/me/sessions/{de_beto}/end", headers=_bearer(claves, datos.ana)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"
    guardada = await _sesion(sesiones, de_beto)
    assert guardada.ended_at is None
    assert guardada.end_reason is None
    assert await _auditorias_de(sesiones, de_beto) == 0


async def test_sesion_ajena_responde_igual_que_una_inexistente(
    cliente: AsyncClient, claves: str, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    """No revela que la sesión existe (SRS §12.6: filtro por dueño en la consulta)."""
    de_beto = await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=5, abierta=True)
    cabeceras = _bearer(claves, datos.ana)

    ajena = await cliente.post(f"{API}/me/sessions/{de_beto}/end", headers=cabeceras)
    inexistente = await cliente.post(f"{API}/me/sessions/{uuid.uuid4()}/end", headers=cabeceras)

    assert ajena.status_code == inexistente.status_code == 404
    assert _sin_instance(ajena) == _sin_instance(inexistente)


# ------------------------------------------- Cerrar sesión web ≠ terminar acceso


async def test_cerrar_sesion_web_no_termina_el_acceso_al_equipo(
    cliente: AsyncClient, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    abierta = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    async with sesiones() as db:
        token = await refresh_tokens.emitir(db, datos.ana.id, "pytest")
        await db.commit()

    resp = await cliente.post(f"{API}/auth/logout", headers={"Cookie": f"{COOKIE_NAME}={token}"})

    assert resp.status_code == 204
    guardada = await _sesion(sesiones, abierta)
    assert guardada.ended_at is None
    assert guardada.end_reason is None
