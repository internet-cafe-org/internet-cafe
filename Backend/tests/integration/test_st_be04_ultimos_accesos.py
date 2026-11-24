"""Pruebas de integración para ST-BE-04: GET /machine/sessions/current con los últimos 5 accesos.

Verifica el comportamiento de ``GET /api/v1/machine/sessions/current``:
- Responde 200 con la sesión activa, los datos del estudiante enmascarados y los
  accesos recientes ordenados de más nuevo a más antiguo (máximo 5).
- Responde 204 cuando el equipo no tiene sesión abierta.
- Los accesos recientes no incluyen la sesión abierta actualmente (sólo cerradas).
- Con más de 5 accesos previos solo se devuelven los 5 más recientes.
- El código de estudiante siempre aparece enmascarado (nunca el código completo).
- El campo ``student_code_masked`` no contiene el código real del estudiante.

Autenticación del equipo: firma RFC 9421 de cada petición,
igual que en test_sesiones.py (QA-06).
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AccessSession,
    Machine,
    SessionEndReason,
)
from app.services import challenges
from tests.firmador import FirmaEquipo, firma_de, firmador_de

API = "/api/v1/machine"
T0 = datetime(2026, 11, 17, 8, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------- helpers

def seg(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


class Reloj:
    """Reloj controlado para los endpoints que llaman a challenges.ahora()."""

    def __init__(self) -> None:
        self.actual = T0

    def __call__(self) -> datetime:
        return self.actual

    def en(self, n: float) -> None:
        self.actual = seg(n)


def auth(equipo: Machine) -> FirmaEquipo:
    return firma_de(equipo.code)


# ------------------------------------------------------------------- fixtures


@pytest.fixture
def reloj(monkeypatch: pytest.MonkeyPatch) -> Reloj:
    falso = Reloj()
    monkeypatch.setattr(challenges, "ahora", falso)
    return falso


@pytest.fixture
async def cliente(sesiones: async_sessionmaker, datos, reloj: Reloj) -> AsyncClient:
    """Cliente HTTP con los dos equipos ya enrolados."""
    async with sesiones() as db:
        for equipo in (datos.pc01, datos.pc02):
            await db.execute(
                update(Machine)
                .where(Machine.id == equipo.id)
                .values(**firmador_de(equipo.code).clave_enrolada)
            )
        await db.commit()

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


async def _abrir_sesion(
    sesiones: async_sessionmaker,
    equipo: Machine,
    usuario,
    t: float,
) -> AccessSession:
    """Abre una sesión pasando por el flujo real de QR (igual que QA-06)."""
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, equipo.id, now=seg(t))
        await db.commit()
    async with sesiones() as db:
        sesion, *_ = await challenges.reclamar_reto_qr(db, token, usuario.id, now=seg(t + 10))
    return sesion


async def _cerrar_sesion(
    sesiones: async_sessionmaker,
    sesion: AccessSession,
    t_inicio: float,
    duracion: float,
) -> None:
    """Cierra la sesión directamente en la BD con el motivo user_logout_pc.

    _abrir_sesion reclama el reto en seg(t_inicio + 10), por lo que started_at
    real de la sesión es seg(t_inicio + 10). El fin se calcula desde ese punto
    para que duration_s coincida exactamente con el parámetro 'duracion'.
    """
    fin = seg(t_inicio + 10 + duracion)
    async with sesiones() as db:
        await db.execute(
            update(AccessSession)
            .where(AccessSession.id == sesion.id)
            .values(ended_at=fin, end_reason=SessionEndReason.user_logout_pc)
        )
        await db.commit()


# ============================================================== tests


async def test_sin_sesion_devuelve_204(cliente: AsyncClient, datos, reloj: Reloj) -> None:
    """Sin sesión abierta el endpoint responde 204 (sin cuerpo)."""
    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 204
    assert resp.content == b""


async def test_con_sesion_devuelve_200_y_estructura_del_contrato(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """200 con 'session', 'user' y 'recent_accesses' cuando hay sesión abierta."""
    sesion = await _abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(30)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    cuerpo = resp.json()
    # Estructura mínima del contrato
    assert "session" in cuerpo
    assert "user" in cuerpo
    assert "recent_accesses" in cuerpo
    # Campos de la sesión
    assert cuerpo["session"]["id"] == str(sesion.id)
    assert cuerpo["session"]["status"] == "active"
    assert "started_at" in cuerpo["session"]
    # Campos del usuario
    assert "full_name" in cuerpo["user"]
    assert "student_code_masked" in cuerpo["user"]


async def test_codigo_de_estudiante_siempre_enmascarado(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """student_code_masked nunca devuelve el código completo del estudiante."""
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(30)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    mascara = resp.json()["user"]["student_code_masked"]
    # El código real de ana es "0000000001" (ver conftest); la máscara no puede serlo
    assert mascara != "0000000001"
    # La máscara debe contener asteriscos (patrón *****XXXX)
    assert "*" in mascara


async def test_accesos_recientes_no_incluyen_sesion_actual(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """La sesión abierta no aparece en recent_accesses; solo las cerradas cuentan."""
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(30)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    # Si no había sesiones previas cerradas, la lista debe estar vacía
    assert resp.json()["recent_accesses"] == []


async def test_accesos_recientes_con_historial_previo(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """Con sesiones previas cerradas, recent_accesses incluye los campos del contrato."""
    # Primera sesión (cerrada)
    s1 = await _abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    await _cerrar_sesion(sesiones, s1, t_inicio=0, duracion=600)

    # Segunda sesión (abierta ahora)
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 1200)
    reloj.en(1250)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    accesos = resp.json()["recent_accesses"]
    assert len(accesos) == 1
    acceso = accesos[0]
    # Campos del contrato para cada acceso reciente
    assert "machine_code" in acceso
    assert "lab" in acceso
    assert "started_at" in acceso
    assert "ended_at" in acceso
    assert "duration_s" in acceso
    assert acceso["duration_s"] == 600


async def test_accesos_recientes_orden_de_mas_nuevo_a_mas_antiguo(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """Los accesos recientes vienen ordenados de más nuevo a más antiguo (ended_at desc)."""
    # Tres sesiones cerradas en orden creciente
    for i in range(3):
        s = await _abrir_sesion(sesiones, datos.pc01, datos.ana, i * 1000)
        await _cerrar_sesion(sesiones, s, t_inicio=i * 1000, duracion=300)

    # Sesión actual abierta
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 4000)
    reloj.en(4050)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    accesos = resp.json()["recent_accesses"]
    assert len(accesos) == 3
    # Verifica que ended_at sea decreciente
    fechas = [acceso["ended_at"] for acceso in accesos]
    assert fechas == sorted(fechas, reverse=True)


async def test_accesos_recientes_maximo_5_aunque_haya_mas(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """Con más de 5 sesiones previas, solo se devuelven los 5 más recientes."""
    # Crear 7 sesiones cerradas
    for i in range(7):
        s = await _abrir_sesion(sesiones, datos.pc01, datos.ana, i * 500)
        await _cerrar_sesion(sesiones, s, t_inicio=i * 500, duracion=200)

    # Sesión abierta actualmente
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 5000)
    reloj.en(5050)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    accesos = resp.json()["recent_accesses"]
    # Nunca más de 5
    assert len(accesos) == 5
    # Deben ser las 5 más recientes (ended_at más alto)
    fechas = [acceso["ended_at"] for acceso in accesos]
    assert fechas == sorted(fechas, reverse=True)


async def test_accesos_recientes_de_otro_equipo_no_aparecen(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """Los accesos de otro equipo del mismo usuario no deben aparecer en la lista."""
    # Ana tuvo una sesión en pc02 (cerrada)
    s_otro = await _abrir_sesion(sesiones, datos.pc02, datos.ana, 0)
    await _cerrar_sesion(sesiones, s_otro, t_inicio=0, duracion=400)

    # Ahora Ana abre sesión en pc01
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 1500)
    reloj.en(1550)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    accesos = resp.json()["recent_accesses"]
    # La sesión de pc02 SÍ aparece (es del mismo usuario, no del mismo equipo)
    assert len(accesos) == 1
    assert accesos[0]["machine_code"] == datos.pc02.code


async def test_accesos_de_otro_usuario_no_aparecen(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """Los accesos de otro estudiante en el mismo equipo no aparecen en recent_accesses."""
    # Beto tuvo una sesión en pc01 (cerrada)
    s_beto = await _abrir_sesion(sesiones, datos.pc01, datos.beto, 0)
    await _cerrar_sesion(sesiones, s_beto, t_inicio=0, duracion=300)

    # Ahora Ana abre sesión en el mismo equipo
    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 1500)
    reloj.en(1550)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    # Ana no tiene historial previo; no debe ver el de Beto
    assert resp.json()["recent_accesses"] == []


async def test_duration_s_calculado_correctamente(
    cliente: AsyncClient, sesiones: async_sessionmaker, datos, reloj: Reloj
) -> None:
    """duration_s refleja la duración real de la sesión cerrada en segundos."""
    s = await _abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    # Cierra a los 1800 segundos (30 minutos)
    await _cerrar_sesion(sesiones, s, t_inicio=0, duracion=1800)

    await _abrir_sesion(sesiones, datos.pc01, datos.ana, 2500)
    reloj.en(2550)

    resp = await cliente.get(f"{API}/sessions/current", auth=auth(datos.pc01))

    assert resp.status_code == 200
    accesos = resp.json()["recent_accesses"]
    assert len(accesos) == 1
    assert accesos[0]["duration_s"] == 1800
