"""QA-06: pruebas de sesiones contra PostgreSQL (HU-10 / BE-09b).

Cubren el latido del equipo, el cierre desde el PC, el reemplazo por otro equipo
(`superseded`) y el cierre por inactividad (RN-01, RN-02, RN-04, RN-07, RN-08).

El tiempo se controla con un reloj falso que reemplaza `challenges.ahora` (lo que usan
los endpoints) o con el parámetro `now` de los servicios: nunca se espera de verdad.
No hay credenciales reales: el equipo se autentica con una credencial ficticia.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AccessSession,
    AuditActorType,
    AuditLog,
    Machine,
    MachineStatus,
    SessionEndReason,
)
from app.security.dependencies import hash_machine_credential
from app.services import challenges
from app.services import sesiones as servicio_sesiones

T0 = datetime(2026, 11, 10, 8, 0, 0, tzinfo=UTC)
CREDENCIAL_PC = "credencial-ficticia-de-pruebas"
API = "/api/v1/machine"
TIMEOUT = settings.heartbeat_timeout_s


def seg(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


class Reloj:
    """Reloj controlado: lo que devuelve `challenges.ahora()` en los endpoints."""

    def __init__(self) -> None:
        self.actual = T0

    def __call__(self) -> datetime:
        return self.actual

    def en(self, n: float) -> None:
        self.actual = seg(n)


@pytest.fixture
def reloj(monkeypatch) -> Reloj:
    falso = Reloj()
    monkeypatch.setattr(challenges, "ahora", falso)
    return falso


@pytest.fixture
async def cliente(sesiones, datos, reloj):
    """Cliente HTTP con los dos equipos de prueba ya con credencial."""
    async with sesiones() as db:
        for equipo in (datos.pc01, datos.pc02):
            await db.execute(
                update(Machine)
                .where(Machine.id == equipo.id)
                .values(key_thumbprint=hash_machine_credential(f"{CREDENCIAL_PC}-{equipo.code}"))
            )
        await db.commit()

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


def auth(equipo) -> dict[str, str]:
    return {
        "X-Machine-Code": equipo.code,
        "X-Machine-Key": f"{CREDENCIAL_PC}-{equipo.code}",
    }


async def abrir_sesion(sesiones: async_sessionmaker, equipo, usuario, t: float) -> AccessSession:
    """Abre una sesión como lo hace el flujo real: QR en `t`, confirmación en `t + 10`."""
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, equipo.id, now=seg(t))
        await db.commit()
    async with sesiones() as db:
        sesion, *_ = await challenges.reclamar_reto_qr(db, token, usuario.id, now=seg(t + 10))
    return sesion


async def leer_sesion(sesiones: async_sessionmaker, session_id) -> AccessSession:
    async with sesiones() as db:
        return (
            await db.execute(select(AccessSession).where(AccessSession.id == session_id))
        ).scalar_one()


async def leer_equipo(sesiones: async_sessionmaker, equipo) -> Machine:
    async with sesiones() as db:
        return (await db.execute(select(Machine).where(Machine.id == equipo.id))).scalar_one()


async def cerrar_inactivas(sesiones, now: datetime, timeout_s: int | None = None) -> int:
    async with sesiones() as db:
        cerradas = await servicio_sesiones.cerrar_sesiones_inactivas(db, now, timeout_s)
        await db.commit()
    return cerradas


async def latido(cliente, equipo, session_id=None):
    cuerpo = {"session_id": str(session_id)} if session_id else None
    return await cliente.post(f"{API}/heartbeat", headers=auth(equipo), json=cuerpo)


# ---------------------------------------------------------------------------
# Latido
# ---------------------------------------------------------------------------


async def test_latido_con_sesion_abierta_la_mantiene_activa(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(70)

    resp = await latido(cliente, datos.pc01)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["session_status"] == "active"
    assert cuerpo["session_id"] == str(sesion.id)
    assert "mode" in cuerpo
    assert (await leer_sesion(sesiones, sesion.id)).last_heartbeat_at == seg(70)
    assert (await leer_equipo(sesiones, datos.pc01)).last_seen_at == seg(70)


async def test_latido_usa_la_hora_del_servidor_y_no_la_del_cliente(
    cliente, sesiones, datos, reloj
):
    """RN-01: el cuerpo no puede traer una hora; el servidor rechaza campos desconocidos."""
    await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(70)

    resp = await cliente.post(
        f"{API}/heartbeat",
        headers=auth(datos.pc01),
        json={"last_heartbeat_at": "2030-01-01T00:00:00Z"},
    )

    assert resp.status_code == 422


async def test_latido_sin_sesion_responde_none(cliente, datos, reloj):
    resp = await latido(cliente, datos.pc01)

    assert resp.status_code == 200
    assert resp.json()["session_status"] == "none"
    assert "session_id" not in resp.json()


async def test_latido_no_toca_la_sesion_de_otro_equipo(cliente, sesiones, datos, reloj):
    ana = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    beto = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)
    reloj.en(100)

    await latido(cliente, datos.pc01)

    assert (await leer_sesion(sesiones, ana.id)).last_heartbeat_at == seg(100)
    assert (await leer_sesion(sesiones, beto.id)).last_heartbeat_at == seg(10)


@pytest.mark.parametrize(
    "motivo", [SessionEndReason.user_logout_web, SessionEndReason.admin_forced]
)
async def test_latido_informa_el_cierre_remoto(cliente, sesiones, datos, reloj, motivo):
    """El equipo se entera de un cierre hecho desde la web o por un admin en su próximo latido."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    async with sesiones() as db:
        assert await servicio_sesiones.cerrar_sesion_abierta(db, sesion.id, motivo, seg(60))
        await db.commit()
    reloj.en(70)

    resp = await latido(cliente, datos.pc01, session_id=sesion.id)

    assert resp.status_code == 200
    assert resp.json()["session_status"] == "ended"
    assert resp.json()["session_id"] == str(sesion.id)
    assert resp.json()["end_reason"] == motivo.value


async def test_latido_no_revela_sesiones_de_otro_equipo(cliente, sesiones, datos, reloj):
    """Preguntar por la sesión cerrada de otro equipo responde `none`, no `ended`."""
    ajena = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)
    async with sesiones() as db:
        await servicio_sesiones.cerrar_sesion_abierta(
            db, ajena.id, SessionEndReason.admin_forced, seg(60)
        )
        await db.commit()
    reloj.en(70)

    resp = await latido(cliente, datos.pc01, session_id=ajena.id)

    assert resp.status_code == 200
    assert resp.json()["session_status"] == "none"
    assert "end_reason" not in resp.json()


async def test_latido_de_equipo_deshabilitado_se_rechaza(cliente, sesiones, datos, reloj):
    """RN-08: un equipo que no está activo no puede enviar latidos."""
    async with sesiones() as db:
        await db.execute(
            update(Machine).where(Machine.id == datos.pc01.id).values(status=MachineStatus.disabled)
        )
        await db.commit()

    resp = await latido(cliente, datos.pc01)

    assert resp.status_code == 403
    assert resp.json()["code"] == "MACHINE_DISABLED"


async def test_latido_sin_credencial_se_rechaza(cliente, datos, reloj):
    resp = await cliente.post(f"{API}/heartbeat")

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_latido_con_credencial_incorrecta_se_rechaza(cliente, datos, reloj):
    cabeceras = {"X-Machine-Code": datos.pc01.code, "X-Machine-Key": "no-es-la-credencial"}

    resp = await cliente.post(f"{API}/heartbeat", headers=cabeceras)

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"


# ---------------------------------------------------------------------------
# Cierre desde el PC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("motivo", ["user_logout_pc", "machine_shutdown"])
async def test_cierre_desde_el_pc_con_cada_motivo(cliente, sesiones, datos, reloj, motivo):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(300)

    resp = await cliente.post(
        f"{API}/sessions/current/end", headers=auth(datos.pc01), json={"reason": motivo}
    )

    assert resp.status_code == 200
    cerrada = resp.json()["session"]
    assert cerrada["id"] == str(sesion.id)
    assert cerrada["status"] == "closed"
    assert cerrada["end_reason"] == motivo
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.ended_at == seg(300)
    assert guardada.end_reason == SessionEndReason(motivo)


async def test_cierre_desde_el_pc_sin_cuerpo_usa_user_logout_pc(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(120)

    resp = await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    assert resp.status_code == 200
    assert resp.json()["session"]["end_reason"] == "user_logout_pc"
    assert (await leer_sesion(sesiones, sesion.id)).end_reason == SessionEndReason.user_logout_pc


async def test_cierre_desde_el_pc_rechaza_motivos_que_no_le_corresponden(
    cliente, sesiones, datos, reloj
):
    """Desde el equipo solo se permite `user_logout_pc` o `machine_shutdown`."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    resp = await cliente.post(
        f"{API}/sessions/current/end", headers=auth(datos.pc01), json={"reason": "admin_forced"}
    )

    assert resp.status_code == 422
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


async def test_cierre_desde_el_pc_sin_sesion_abierta(cliente, datos, reloj):
    resp = await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"


async def test_segundo_cierre_no_pisa_el_primero(cliente, sesiones, datos, reloj):
    """El primero gana: reintentar el cierre no cambia la hora ni el motivo."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(100)
    primero = await cliente.post(
        f"{API}/sessions/current/end", headers=auth(datos.pc01), json={"reason": "machine_shutdown"}
    )
    reloj.en(200)

    segundo = await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    assert primero.status_code == 200
    assert segundo.status_code == 404
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.ended_at == seg(100)
    assert guardada.end_reason == SessionEndReason.machine_shutdown


async def test_cierre_desde_un_equipo_no_cierra_la_sesion_de_otro(cliente, sesiones, datos, reloj):
    beto = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)
    reloj.en(100)

    resp = await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    assert resp.status_code == 404
    assert (await leer_sesion(sesiones, beto.id)).ended_at is None


async def test_tras_cerrar_desde_el_pc_ya_no_hay_sesion_actual(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    assert (await cliente.get(f"{API}/sessions/current", headers=auth(datos.pc01))).status_code == 200
    reloj.en(100)
    await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    actual = await cliente.get(f"{API}/sessions/current", headers=auth(datos.pc01))
    siguiente = await latido(cliente, datos.pc01, session_id=sesion.id)

    assert actual.status_code == 204
    assert siguiente.json()["session_status"] == "ended"
    assert siguiente.json()["end_reason"] == "user_logout_pc"


async def test_cierre_desde_el_pc_queda_auditado(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(100)

    await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    async with sesiones() as db:
        filas = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.target_id == sesion.id, AuditLog.action == "session_ended"
                )
            )
        ).scalars().all()
    assert len(filas) == 1
    assert filas[0].actor_type == AuditActorType.machine
    assert filas[0].actor_id == datos.pc01.id
    assert filas[0].metadata_info == {"end_reason": "user_logout_pc"}


# ---------------------------------------------------------------------------
# Reemplazo (`superseded`, RN-02 / RF-SES-04)
# ---------------------------------------------------------------------------


async def test_confirmar_en_otro_equipo_cierra_la_sesion_anterior_como_superseded(
    cliente, sesiones, datos, reloj
):
    anterior = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, datos.pc02.id, now=seg(90))
        await db.commit()

    async with sesiones() as db:
        nueva, *_ = await challenges.reclamar_reto_qr(db, token, datos.ana.id, now=seg(100))

    cerrada = await leer_sesion(sesiones, anterior.id)
    assert cerrada.end_reason == SessionEndReason.superseded
    assert cerrada.ended_at == seg(100)
    assert (await leer_sesion(sesiones, nueva.id)).ended_at is None
    reloj.en(110)
    del_pc01 = (await latido(cliente, datos.pc01, session_id=anterior.id)).json()
    del_pc02 = (await latido(cliente, datos.pc02)).json()
    assert del_pc01["session_status"] == "ended"
    assert del_pc01["end_reason"] == "superseded"
    assert del_pc02["session_status"] == "active"


async def test_equipo_ocupado_no_reemplaza_la_sesion_del_estudiante(sesiones, datos):
    """Si el equipo destino está ocupado, la sesión previa del estudiante sigue abierta."""
    ana = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    beto = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, datos.pc02.id, now=seg(20))
        await db.commit()

    with pytest.raises(challenges.MachineBusyError):
        async with sesiones() as db:
            await challenges.reclamar_reto_qr(db, token, datos.ana.id, now=seg(30))

    assert (await leer_sesion(sesiones, ana.id)).ended_at is None
    assert (await leer_sesion(sesiones, beto.id)).ended_at is None


async def test_equipo_que_pide_nuevo_qr_cierra_su_sesion_huerfana_como_superseded(
    sesiones, datos
):
    """RN-02: si el QR de la sesión ya venció y el equipo pide otro, la sesión quedó huérfana."""
    huerfana = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    async with sesiones() as db:
        await challenges.crear_reto(db, datos.pc01.id, now=seg(120))
        await db.commit()

    cerrada = await leer_sesion(sesiones, huerfana.id)
    assert cerrada.end_reason == SessionEndReason.superseded
    assert cerrada.ended_at == seg(120)


async def test_nuevo_qr_con_el_reto_de_la_sesion_vigente_no_la_cierra(sesiones, datos):
    """Mientras el QR con el que se abrió la sesión sigue vigente, no es huérfana."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    async with sesiones() as db:
        await challenges.crear_reto(db, datos.pc01.id, now=seg(30))
        await db.commit()

    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


# ---------------------------------------------------------------------------
# Inactividad (RN-07)
# ---------------------------------------------------------------------------


async def test_sin_latido_antes_del_limite_la_sesion_sigue_abierta(sesiones, datos):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)  # último latido: t = 10

    cerradas = await cerrar_inactivas(sesiones, seg(10 + TIMEOUT - 1))

    assert cerradas == 0
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


async def test_en_el_limite_exacto_se_cierra_con_la_hora_del_ultimo_latido(sesiones, datos):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)  # último latido: t = 10

    cerradas = await cerrar_inactivas(sesiones, seg(10 + TIMEOUT))

    assert cerradas == 1
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.end_reason == SessionEndReason.heartbeat_timeout
    assert guardada.ended_at == seg(10)
    assert guardada.ended_at == guardada.last_heartbeat_at


async def test_un_latido_reinicia_el_plazo_de_inactividad(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(100)
    await latido(cliente, datos.pc01)

    antes = await cerrar_inactivas(sesiones, seg(100 + TIMEOUT - 1))
    en_el_limite = await cerrar_inactivas(sesiones, seg(100 + TIMEOUT))

    assert antes == 0
    assert en_el_limite == 1
    assert (await leer_sesion(sesiones, sesion.id)).ended_at == seg(100)


async def test_el_plazo_de_inactividad_se_puede_configurar(sesiones, datos):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    assert await cerrar_inactivas(sesiones, seg(10 + 29), timeout_s=30) == 0
    assert await cerrar_inactivas(sesiones, seg(10 + 30), timeout_s=30) == 1
    assert (await leer_sesion(sesiones, sesion.id)).ended_at == seg(10)


async def test_la_inactividad_no_toca_sesiones_ya_cerradas(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(50)
    await cliente.post(f"{API}/sessions/current/end", headers=auth(datos.pc01))

    cerradas = await cerrar_inactivas(sesiones, seg(10_000))

    assert cerradas == 0
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.end_reason == SessionEndReason.user_logout_pc
    assert guardada.ended_at == seg(50)


async def test_solo_se_cierran_las_sesiones_inactivas(cliente, sesiones, datos, reloj):
    ana = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    beto = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)
    reloj.en(10 + TIMEOUT - 20)
    await latido(cliente, datos.pc02)  # solo el equipo de Beto sigue latiendo

    cerradas = await cerrar_inactivas(sesiones, seg(10 + TIMEOUT))

    assert cerradas == 1
    assert (await leer_sesion(sesiones, ana.id)).end_reason == SessionEndReason.heartbeat_timeout
    assert (await leer_sesion(sesiones, beto.id)).ended_at is None


async def test_cierre_por_inactividad_queda_auditado_como_sistema(sesiones, datos):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    await cerrar_inactivas(sesiones, seg(10 + TIMEOUT))

    async with sesiones() as db:
        filas = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.target_id == sesion.id, AuditLog.action == "session_ended"
                )
            )
        ).scalars().all()
    assert len(filas) == 1
    assert filas[0].actor_type == AuditActorType.system
    assert filas[0].actor_id is None
    assert filas[0].metadata_info == {"end_reason": "heartbeat_timeout"}


async def test_el_equipo_se_entera_del_cierre_por_inactividad(cliente, sesiones, datos, reloj):
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    await cerrar_inactivas(sesiones, seg(10 + TIMEOUT))
    reloj.en(10 + TIMEOUT + 5)

    resp = await latido(cliente, datos.pc01, session_id=sesion.id)

    assert resp.json()["session_status"] == "ended"
    assert resp.json()["end_reason"] == "heartbeat_timeout"


async def test_tras_la_inactividad_el_equipo_queda_libre_para_otro_estudiante(sesiones, datos):
    await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    ahora = 10 + TIMEOUT
    await cerrar_inactivas(sesiones, seg(ahora))

    nueva = await abrir_sesion(sesiones, datos.pc01, datos.beto, ahora + 5)

    assert nueva.user_id == datos.beto.id
    assert (await leer_sesion(sesiones, nueva.id)).ended_at is None