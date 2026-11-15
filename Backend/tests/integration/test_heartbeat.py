"""Pruebas de integración del latido del equipo (BE-08, contrato v0.2).

La lógica del latido llegó en BE-18; aquí se prueba por HTTP con un equipo enrolado
y la base de pruebas real (mismos fixtures `sesiones` y `datos` que QA-05):

- sin credenciales: 401 MACHINE_SIGNATURE_INVALID (lo que devuelve `require_machine`);
- con sesión abierta: `active`, y se actualizan `last_seen_at` y `last_heartbeat_at`;
- `session_id` de una sesión cerrada: `ended` con su `end_reason`;
- sin sesión: `none`;
- `session_id` de otro equipo: `none`, sin exponer datos.

El tiempo se controla reemplazando `challenges.ahora`, nunca esperando de verdad.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.database import obtener_base_datos
from app.main import app
from app.models import AccessSession, Machine, MachineMode, SessionEndReason
from app.security.dependencies import hash_machine_credential
from app.services import challenges
from app.services import sesiones as servicio_sesiones

RUTA = "/api/v1/machine/heartbeat"
CREDENCIAL_PC01 = "credencial-de-prueba-pc01"
T0 = datetime(2026, 11, 3, 10, 0, 0, tzinfo=UTC)


def seg(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


def fijar_hora(monkeypatch, momento: datetime) -> None:
    monkeypatch.setattr(challenges, "ahora", lambda: momento)


@pytest.fixture
async def cliente(sesiones) -> AsyncIterator[AsyncClient]:
    async def base_de_prueba():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = base_de_prueba
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(obtener_base_datos, None)


@pytest.fixture
async def cabecera_pc01(sesiones, datos) -> dict[str, str]:
    """Enrola el PC01 (guarda el hash de su credencial) y devuelve sus cabeceras."""
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == datos.pc01.id)
            .values(key_thumbprint=hash_machine_credential(CREDENCIAL_PC01))
        )
        await db.commit()
    return {"X-Machine-Code": datos.pc01.code, "X-Machine-Key": CREDENCIAL_PC01}


async def abrir_sesion(sesiones, machine, usuario, now: datetime) -> AccessSession:
    """Lo que hacen POST /machine/challenges y POST /scan/claim: deja la sesión abierta."""
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, machine.id, now=now)
        await db.commit()
    async with sesiones() as db:
        sesion, *_ = await challenges.reclamar_reto_qr(
            db, token, usuario.id, now=now + timedelta(seconds=5)
        )
    return sesion


async def cerrar_sesion(sesiones, machine, motivo: SessionEndReason, now: datetime) -> None:
    async with sesiones() as db:
        await servicio_sesiones.cerrar_sesion_de_equipo(db, machine.id, motivo, now)
        await db.commit()


# ---------------------------------------------------------------------------
# Sin credenciales
# ---------------------------------------------------------------------------


async def test_latido_sin_credenciales_da_401(async_client: AsyncClient):
    """`require_machine` rechaza la petición sin cabeceras con 401 MACHINE_SIGNATURE_INVALID."""
    r = await async_client.post(RUTA, json={})

    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "MACHINE_SIGNATURE_INVALID"


# ---------------------------------------------------------------------------
# Camino feliz
# ---------------------------------------------------------------------------


async def test_latido_con_sesion_abierta(cliente, sesiones, datos, cabecera_pc01, monkeypatch):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, T0)
    fijar_hora(monkeypatch, seg(30))

    r = await cliente.post(RUTA, json={"session_id": str(sesion.id)}, headers=cabecera_pc01)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["session_status"] == "active"
    assert cuerpo["session_id"] == str(sesion.id)
    assert "end_reason" not in cuerpo
    assert datetime.fromisoformat(cuerpo["server_time"]) == seg(30)
    async with sesiones() as db:
        sesion_bd = await db.get(AccessSession, sesion.id)
        equipo_bd = await db.get(Machine, datos.pc01.id)
    assert MachineMode(cuerpo["mode"]) == equipo_bd.mode
    assert sesion_bd.last_heartbeat_at == seg(30)
    assert equipo_bd.last_seen_at == seg(30)


async def test_latido_con_sesion_cerrada_informa_ended(
    cliente, sesiones, datos, cabecera_pc01, monkeypatch
):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, T0)
    await cerrar_sesion(sesiones, datos.pc01, SessionEndReason.superseded, seg(20))
    fijar_hora(monkeypatch, seg(30))

    r = await cliente.post(RUTA, json={"session_id": str(sesion.id)}, headers=cabecera_pc01)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["session_status"] == "ended"
    assert cuerpo["session_id"] == str(sesion.id)
    assert cuerpo["end_reason"] == SessionEndReason.superseded.value


async def test_latido_sin_sesion_responde_none(cliente, datos, cabecera_pc01, monkeypatch):
    fijar_hora(monkeypatch, seg(30))

    r = await cliente.post(RUTA, json={}, headers=cabecera_pc01)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["session_status"] == "none"
    assert "session_id" not in cuerpo
    assert "end_reason" not in cuerpo


async def test_latido_con_sesion_de_otro_equipo_responde_none(
    cliente, sesiones, datos, cabecera_pc01, monkeypatch
):
    """El `session_id` solo se busca entre las sesiones de ESTE equipo."""
    ajena = await abrir_sesion(sesiones, datos.pc02, datos.beto, T0)
    await cerrar_sesion(sesiones, datos.pc02, SessionEndReason.superseded, seg(20))
    fijar_hora(monkeypatch, seg(30))

    r = await cliente.post(RUTA, json={"session_id": str(ajena.id)}, headers=cabecera_pc01)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["session_status"] == "none"
    assert "session_id" not in cuerpo
    assert "end_reason" not in cuerpo
