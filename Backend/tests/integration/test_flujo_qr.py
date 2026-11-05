"""Pruebas de integración del flujo QR contra PostgreSQL (QA-05 / HU-09).

Cubren los casos de RF-QR-02, RF-SES-02, RF-SES-03, RN-02, RN-03 y RN-06 y la
sección 15.2 del SRS: QR vencido, usado, de otro equipo, confirmaciones
concurrentes, `superseded`, `MACHINE_BUSY`, máximo 2 vigentes y la carrera
entre la confirmación y la rotación del QR.

El tiempo se controla con el parámetro `now` del servicio o reemplazando
`challenges.ahora`, nunca esperando de verdad.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import obtener_base_datos
from app.main import app
from app.models import AccessSession, ChallengeStatus, LoginChallenge, SessionEndReason
from app.services import challenges

T0 = datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC)


def seg(n: float) -> datetime:
    return T0 + timedelta(seconds=n)


async def crear_qr(sesiones: async_sessionmaker, machine, now: datetime) -> str:
    """Lo que hace POST /machine/challenges: crea el reto y confirma."""
    async with sesiones() as db:
        _, token = await challenges.crear_reto(db, machine.id, now=now)
        await db.commit()
    return token


async def confirmar(sesiones: async_sessionmaker, token: str, usuario, now: datetime):
    """Lo que hace POST /scan/claim, cada llamada con su propia conexión."""
    async with sesiones() as db:
        return await challenges.reclamar_reto_qr(db, token, usuario.id, now=now)


async def estado_reto(sesiones: async_sessionmaker, token: str) -> ChallengeStatus:
    async with sesiones() as db:
        return (
            await db.execute(
                select(LoginChallenge.status).where(
                    LoginChallenge.token_hash == challenges.hash_token(token)
                )
            )
        ).scalar_one()


async def sesiones_activas(sesiones: async_sessionmaker, machine) -> list[AccessSession]:
    async with sesiones() as db:
        return list(
            (
                await db.execute(
                    select(AccessSession).where(
                        AccessSession.machine_id == machine.id,
                        AccessSession.ended_at.is_(None),
                    )
                )
            ).scalars()
        )


# ---------------------------------------------------------------------------
# Camino feliz
# ---------------------------------------------------------------------------


async def test_confirmar_qr_vigente_abre_sesion(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)

    sesion, machine, sala, idempotente = await confirmar(sesiones, token, datos.ana, seg(10))

    assert not idempotente
    assert machine.code == "LAB-TEST-PC01"
    assert sala == "Sala de pruebas"
    assert sesion.user_id == datos.ana.id
    assert await estado_reto(sesiones, token) == ChallengeStatus.approved
    assert [s.id for s in await sesiones_activas(sesiones, datos.pc01)] == [sesion.id]


# ---------------------------------------------------------------------------
# QR vencido (RF-QR-02)
# ---------------------------------------------------------------------------


async def test_qr_vencido_se_rechaza(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)

    with pytest.raises(challenges.ChallengeExpiredError):
        await confirmar(sesiones, token, datos.ana, seg(60))

    assert await sesiones_activas(sesiones, datos.pc01) == []


async def test_qr_un_segundo_antes_de_vencer_se_acepta(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)

    await confirmar(sesiones, token, datos.ana, seg(59))

    assert len(await sesiones_activas(sesiones, datos.pc01)) == 1


# ---------------------------------------------------------------------------
# QR usado
# ---------------------------------------------------------------------------


async def test_qr_usado_por_otro_estudiante_se_rechaza(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)
    await confirmar(sesiones, token, datos.ana, seg(5))

    with pytest.raises(challenges.ChallengeAlreadyUsedError):
        await confirmar(sesiones, token, datos.beto, seg(6))

    activas = await sesiones_activas(sesiones, datos.pc01)
    assert [s.user_id for s in activas] == [datos.ana.id]


async def test_qr_usado_por_el_mismo_estudiante_es_idempotente(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)
    primera, *_ = await confirmar(sesiones, token, datos.ana, seg(5))

    segunda, _, _, idempotente = await confirmar(sesiones, token, datos.ana, seg(6))

    assert idempotente
    assert segunda.id == primera.id
    assert len(await sesiones_activas(sesiones, datos.pc01)) == 1


# ---------------------------------------------------------------------------
# QR de otro equipo (SRS §15.2)
# ---------------------------------------------------------------------------


async def test_qr_de_un_equipo_no_afecta_a_otro(sesiones, datos):
    token_pc01 = await crear_qr(sesiones, datos.pc01, T0)
    token_pc02 = await crear_qr(sesiones, datos.pc02, T0)

    sesion, machine, _, _ = await confirmar(sesiones, token_pc01, datos.ana, seg(5))

    assert machine.id == datos.pc01.id
    assert sesion.machine_id == datos.pc01.id
    assert await sesiones_activas(sesiones, datos.pc02) == []
    # El QR del PC02 no se cancela al aprobar el del PC01 (RN-06 es por equipo)
    assert await estado_reto(sesiones, token_pc02) == ChallengeStatus.pending

    await confirmar(sesiones, token_pc02, datos.beto, seg(6))
    activas = await sesiones_activas(sesiones, datos.pc02)
    assert [s.user_id for s in activas] == [datos.beto.id]


# ---------------------------------------------------------------------------
# Confirmación concurrente
# ---------------------------------------------------------------------------


async def test_dos_estudiantes_confirman_el_mismo_qr_a_la_vez(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)

    resultados = await asyncio.gather(
        confirmar(sesiones, token, datos.ana, seg(5)),
        confirmar(sesiones, token, datos.beto, seg(5)),
        return_exceptions=True,
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert len(errores) == 1
    assert isinstance(errores[0], challenges.ChallengeAlreadyUsedError)
    assert len(await sesiones_activas(sesiones, datos.pc01)) == 1


async def test_el_mismo_estudiante_confirma_dos_veces_a_la_vez(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)

    resultados = await asyncio.gather(
        confirmar(sesiones, token, datos.ana, seg(5)),
        confirmar(sesiones, token, datos.ana, seg(5)),
        return_exceptions=True,
    )

    assert not [r for r in resultados if isinstance(r, BaseException)]
    assert sorted(r[3] for r in resultados) == [False, True]
    assert resultados[0][0].id == resultados[1][0].id
    assert len(await sesiones_activas(sesiones, datos.pc01)) == 1


# ---------------------------------------------------------------------------
# superseded (RF-SES-02 / RN-03)
# ---------------------------------------------------------------------------


async def test_confirmar_en_otro_equipo_cierra_la_sesion_anterior(sesiones, datos):
    token_pc01 = await crear_qr(sesiones, datos.pc01, T0)
    anterior, *_ = await confirmar(sesiones, token_pc01, datos.ana, seg(5))
    token_pc02 = await crear_qr(sesiones, datos.pc02, seg(20))

    nueva, *_ = await confirmar(sesiones, token_pc02, datos.ana, seg(30))

    async with sesiones() as db:
        cerrada = await db.get(AccessSession, anterior.id)
    assert cerrada.ended_at == seg(30)
    assert cerrada.end_reason == SessionEndReason.superseded
    assert await sesiones_activas(sesiones, datos.pc01) == []
    assert [s.id for s in await sesiones_activas(sesiones, datos.pc02)] == [nueva.id]


# ---------------------------------------------------------------------------
# MACHINE_BUSY (RF-SES-03)
# ---------------------------------------------------------------------------


async def test_equipo_ocupado_responde_machine_busy(sesiones, datos):
    token_ana = await crear_qr(sesiones, datos.pc01, T0)
    await confirmar(sesiones, token_ana, datos.ana, seg(5))
    # El reto de origen sigue vigente, así que RN-02 no cierra la sesión
    token_beto = await crear_qr(sesiones, datos.pc01, seg(10))

    with pytest.raises(challenges.MachineBusyError):
        await confirmar(sesiones, token_beto, datos.beto, seg(15))

    activas = await sesiones_activas(sesiones, datos.pc01)
    assert [s.user_id for s in activas] == [datos.ana.id]


async def test_dos_estudiantes_confirman_los_dos_qr_vigentes_a_la_vez(sesiones, datos):
    token_1 = await crear_qr(sesiones, datos.pc01, T0)
    token_2 = await crear_qr(sesiones, datos.pc01, seg(45))

    resultados = await asyncio.gather(
        confirmar(sesiones, token_1, datos.ana, seg(50)),
        confirmar(sesiones, token_2, datos.beto, seg(50)),
        return_exceptions=True,
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1, resultados
    assert len(errores) == 1
    # El que pierde ve el equipo ocupado o su reto ya cancelado (RN-06)
    assert isinstance(
        errores[0], (challenges.MachineBusyError, challenges.ChallengeAlreadyUsedError)
    ), repr(errores[0])
    assert len(await sesiones_activas(sesiones, datos.pc01)) == 1


# ---------------------------------------------------------------------------
# Máximo 2 vigentes (RF-QR-02 / RN-06)
# ---------------------------------------------------------------------------


async def test_tercer_qr_cancela_el_mas_viejo(sesiones, datos):
    token_1 = await crear_qr(sesiones, datos.pc01, T0)
    token_2 = await crear_qr(sesiones, datos.pc01, seg(5))
    token_3 = await crear_qr(sesiones, datos.pc01, seg(10))

    assert await estado_reto(sesiones, token_1) == ChallengeStatus.cancelled
    assert await estado_reto(sesiones, token_2) == ChallengeStatus.pending
    assert await estado_reto(sesiones, token_3) == ChallengeStatus.pending
    async with sesiones() as db:
        vigentes = (
            await db.execute(
                select(func.count()).where(
                    LoginChallenge.machine_id == datos.pc01.id,
                    LoginChallenge.status == ChallengeStatus.pending,
                )
            )
        ).scalar_one()
    assert vigentes == 2

    with pytest.raises(challenges.ChallengeAlreadyUsedError):
        await confirmar(sesiones, token_1, datos.ana, seg(11))


async def test_qr_reemplazado_sigue_valido_hasta_vencer(sesiones, datos):
    viejo = await crear_qr(sesiones, datos.pc01, T0)
    await crear_qr(sesiones, datos.pc01, seg(45))  # rotación normal

    await confirmar(sesiones, viejo, datos.ana, seg(55))

    assert await estado_reto(sesiones, viejo) == ChallengeStatus.approved


async def test_al_aprobar_se_cancelan_los_demas_pendientes(sesiones, datos):
    token_1 = await crear_qr(sesiones, datos.pc01, T0)
    token_2 = await crear_qr(sesiones, datos.pc01, seg(45))

    await confirmar(sesiones, token_2, datos.ana, seg(50))

    assert await estado_reto(sesiones, token_1) == ChallengeStatus.cancelled


# ---------------------------------------------------------------------------
# RN-02: crear un reto cierra la sesión que quedó abierta en el equipo
# ---------------------------------------------------------------------------


async def test_rn02_cierra_la_sesion_si_su_reto_de_origen_vencio(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)
    sesion, *_ = await confirmar(sesiones, token, datos.ana, seg(5))

    await crear_qr(sesiones, datos.pc01, seg(61))

    async with sesiones() as db:
        cerrada = await db.get(AccessSession, sesion.id)
    assert cerrada.ended_at == seg(61)
    assert cerrada.end_reason == SessionEndReason.superseded


async def test_rn02_respeta_la_sesion_si_su_reto_de_origen_sigue_vigente(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc01, T0)
    sesion, *_ = await confirmar(sesiones, token, datos.ana, seg(5))

    await crear_qr(sesiones, datos.pc01, seg(30))

    assert [s.id for s in await sesiones_activas(sesiones, datos.pc01)] == [sesion.id]


async def test_rn02_no_toca_sesiones_de_otro_equipo(sesiones, datos):
    token = await crear_qr(sesiones, datos.pc02, T0)
    await confirmar(sesiones, token, datos.ana, seg(5))

    await crear_qr(sesiones, datos.pc01, seg(120))

    assert len(await sesiones_activas(sesiones, datos.pc02)) == 1


# ---------------------------------------------------------------------------
# Carrera con la rotación
# ---------------------------------------------------------------------------


async def test_rotacion_antes_de_confirmar_el_qr_cancelado(sesiones, datos):
    """El PC rota y cancela el QR viejo justo antes de que el estudiante confirme."""
    viejo = await crear_qr(sesiones, datos.pc01, T0)
    await crear_qr(sesiones, datos.pc01, seg(5))
    await crear_qr(sesiones, datos.pc01, seg(10))  # cancela `viejo`

    with pytest.raises(challenges.ChallengeAlreadyUsedError):
        await confirmar(sesiones, viejo, datos.ana, seg(10))

    assert await sesiones_activas(sesiones, datos.pc01) == []


async def test_rotacion_durante_la_confirmacion_no_cancela_el_reto_aprobado(
    sesiones, datos, monkeypatch
):
    """La rotación llega mientras la confirmación del QR viejo tiene el reto bloqueado.

    Se pausa la confirmación justo antes del COMMIT (en la auditoría) para que
    la rotación quede esperando el bloqueo del reto. Al terminar, el reto debe
    seguir `approved` y su sesión abierta.
    """
    viejo = await crear_qr(sesiones, datos.pc01, T0)
    await crear_qr(sesiones, datos.pc01, seg(5))

    en_auditoria = asyncio.Event()
    continuar = asyncio.Event()
    audit_original = challenges.audit

    async def audit_pausado(**kwargs):
        en_auditoria.set()
        await continuar.wait()
        await audit_original(**kwargs)

    monkeypatch.setattr(challenges, "audit", audit_pausado)

    confirmacion = asyncio.create_task(confirmar(sesiones, viejo, datos.ana, seg(10)))
    await asyncio.wait_for(en_auditoria.wait(), timeout=5)
    rotacion = asyncio.create_task(crear_qr(sesiones, datos.pc01, seg(10)))
    await asyncio.sleep(0.5)  # la rotación queda bloqueada en el UPDATE del reto viejo
    continuar.set()
    sesion, *_ = await asyncio.wait_for(confirmacion, timeout=5)
    await asyncio.wait_for(rotacion, timeout=5)

    assert [s.id for s in await sesiones_activas(sesiones, datos.pc01)] == [sesion.id]
    assert await estado_reto(sesiones, viejo) == ChallengeStatus.approved


# ---------------------------------------------------------------------------
# Por HTTP: status y `code` RFC 9457
# ---------------------------------------------------------------------------


@pytest.fixture
async def cliente(sesiones) -> AsyncIterator[AsyncClient]:
    async def base_de_prueba():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = base_de_prueba
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(obtener_base_datos, None)


def fijar_hora(monkeypatch, momento: datetime) -> None:
    monkeypatch.setattr(challenges, "ahora", lambda: momento)


async def test_http_claim_camino_feliz_y_repeticion(cliente, datos, monkeypatch):
    fijar_hora(monkeypatch, T0)
    r = await cliente.post("/api/v1/machine/challenges", headers={"x-machine-code": "LAB-TEST-PC01"})
    assert r.status_code == 201
    token = r.json()["qr_url"].split("#", 1)[1]
    cabecera = {"x-user-id": str(datos.ana.id)}

    r = await cliente.post("/api/v1/scan/preview", json={"token": token}, headers=cabecera)
    assert r.status_code == 200
    assert r.json()["machine"] == {"code": "LAB-TEST-PC01", "lab": "Sala de pruebas"}

    r = await cliente.post("/api/v1/scan/claim", json={"token": token}, headers=cabecera)
    assert r.status_code == 201
    assert r.json()["session"]["machine"]["code"] == "LAB-TEST-PC01"

    r = await cliente.post("/api/v1/scan/claim", json={"token": token}, headers=cabecera)
    assert r.status_code == 200


@pytest.mark.parametrize(
    ("escenario", "status", "code"),
    [
        ("vencido", 410, "CHALLENGE_EXPIRED"),
        ("usado", 409, "CHALLENGE_ALREADY_USED"),
        ("ocupado", 409, "MACHINE_BUSY"),
        ("inexistente", 404, "CHALLENGE_NOT_FOUND"),
    ],
)
async def test_http_claim_errores(cliente, sesiones, datos, monkeypatch, escenario, status, code):
    token = await crear_qr(sesiones, datos.pc01, T0)
    if escenario == "usado":
        await confirmar(sesiones, token, datos.ana, seg(5))
    if escenario == "ocupado":
        await confirmar(sesiones, token, datos.ana, seg(5))
        token = await crear_qr(sesiones, datos.pc01, seg(10))
    if escenario == "inexistente":
        token = "token-que-no-existe"
    fijar_hora(monkeypatch, seg(61) if escenario == "vencido" else seg(20))

    r = await cliente.post(
        "/api/v1/scan/claim",
        json={"token": token},
        headers={"x-user-id": str(datos.beto.id)},
    )

    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == code
    assert token not in r.text
