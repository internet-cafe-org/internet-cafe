"""Pruebas de la tarea periódica de inactividad (BE-09b, RN-07).

El tiempo se controla con el parámetro ``now``: nunca se espera de verdad.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AccessSession, ChallengeStatus, LoginChallenge, SessionEndReason
from app.services import challenges, inactividad

T0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def sin_actividad():
    """Cada prueba empieza sin actividad en memoria."""
    inactividad.reiniciar()
    yield
    inactividad.reiniciar()


async def _sesion(sesiones, machine, usuario, now: datetime) -> AccessSession:
    """Crea un reto y lo confirma, como hacen ``/machine/challenges`` y ``/scan/claim``.

    Args:
        sesiones: Fábrica de sesiones de la base de pruebas.
        machine: Equipo de las fixtures.
        usuario: Estudiante de las fixtures.
        now: Hora de la confirmación.

    Returns:
        La sesión creada.
    """
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, machine.id, now=now)
        await db.commit()
    async with sesiones() as db:
        sesion, *_ = await challenges.reclamar_reto_qr(db, token, usuario.id, now=now)
        return sesion


async def _leer(sesiones, session_id) -> AccessSession:
    """Lee una sesión desde la base.

    Args:
        sesiones: Fábrica de sesiones de la base de pruebas.
        session_id: Id de la sesión.

    Returns:
        La sesión con sus valores actuales.
    """
    async with sesiones() as db:
        return await db.get(AccessSession, session_id)


async def test_barrido_cierra_solo_las_sesiones_sin_latido(sesiones, datos):
    """Cierra la que no tuvo latido en 3 min con ended_at = último latido; deja la otra."""
    vieja = await _sesion(sesiones, datos.pc01, datos.ana, T0)
    nueva = await _sesion(sesiones, datos.pc02, datos.beto, T0 + timedelta(minutes=2))

    async with sesiones() as db:
        resultado = await inactividad.barrer(db, now=T0 + timedelta(minutes=3, seconds=1))

    assert resultado.sesiones_cerradas == 1
    assert resultado.sesiones_abiertas == 1
    cerrada = await _leer(sesiones, vieja.id)
    assert cerrada.end_reason == SessionEndReason.heartbeat_timeout
    assert cerrada.ended_at == cerrada.last_heartbeat_at
    assert (await _leer(sesiones, nueva.id)).ended_at is None
    assert inactividad.hay_actividad()


async def test_barrido_expira_retos_vencidos(sesiones, datos):
    """Los retos pending vencidos pasan a expired."""
    async with sesiones() as db:
        reto, _ = await challenges.crear_reto(db, datos.pc01.id, now=T0)
        await db.commit()

    async with sesiones() as db:
        resultado = await inactividad.barrer(db, now=T0 + timedelta(minutes=5))

    assert resultado.retos_expirados == 1
    async with sesiones() as db:
        assert await db.scalar(select(LoginChallenge.status)) == ChallengeStatus.expired


async def test_sin_sesiones_abiertas_se_apaga_la_actividad(sesiones, datos):
    """Si no queda nada abierto, los ciclos siguientes no tocan la base."""
    await _sesion(sesiones, datos.pc01, datos.ana, T0)
    inactividad.marcar_actividad()

    async with sesiones() as db:
        resultado = await inactividad.barrer(db, now=T0 + timedelta(minutes=10))

    assert resultado.sesiones_cerradas == 1
    assert resultado.sesiones_abiertas == 0
    assert not inactividad.hay_actividad()


async def test_ciclo_sin_actividad_no_consulta_la_base():
    """Sin actividad en memoria el ciclo ni siquiera abre una sesión de base."""

    def fabrica_que_falla():
        raise AssertionError("no debió abrir una sesión de base")

    assert await inactividad.ciclo(fabrica_que_falla) is None


async def test_ciclo_con_actividad_barre(sesiones, datos):
    """Con actividad, el ciclo barre con la hora real (la sesión es de hace una hora)."""
    sesion = await _sesion(sesiones, datos.pc01, datos.ana, challenges.ahora() - timedelta(hours=1))
    inactividad.marcar_actividad()

    resultado = await inactividad.ciclo(sesiones)

    assert resultado is not None and resultado.sesiones_cerradas == 1
    assert (await _leer(sesiones, sesion.id)).end_reason == SessionEndReason.heartbeat_timeout


async def test_barrido_inicial_no_rompe_el_arranque_si_la_base_falla():
    """Si la base no responde al arrancar, se deja la actividad marcada para reintentar."""

    def fabrica_caida():
        raise ConnectionError("base caída")

    await inactividad.barrido_inicial(fabrica_caida)

    assert inactividad.hay_actividad()


async def test_el_latido_con_sesion_marca_actividad(cliente_equipo, sesiones, datos):
    """``POST /machine/heartbeat`` con sesión abierta enciende la marca."""
    await _sesion(sesiones, datos.pc01, datos.ana, challenges.ahora())
    inactividad.reiniciar()

    r = await cliente_equipo.post("/api/v1/machine/heartbeat")

    assert r.status_code == 200
    assert r.json()["session_status"] == "active"
    assert inactividad.hay_actividad()


@pytest.fixture
async def cliente_equipo(sesiones, datos):
    """Cliente HTTP autenticado como ``pc01`` con una credencial provisional."""
    from httpx import ASGITransport, AsyncClient

    from app.database import obtener_base_datos
    from app.main import app
    from app.models import Machine
    from app.security.dependencies import hash_machine_credential

    async with sesiones() as db:
        (await db.get(Machine, datos.pc01.id)).credential_hash = hash_machine_credential("clave-pc01")
        await db.commit()

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    cabeceras = {"X-Machine-Code": datos.pc01.code, "X-Machine-Key": "clave-pc01"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=cabeceras) as c:
        yield c
    app.dependency_overrides.clear()
