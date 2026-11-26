"""ST-BE-01 contra PostgreSQL real y un proveedor Resend simulado."""

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from app import database, main
from app.config import settings
from app.models import EmailOutbox
from app.services import outbox, pii
from app.services.correo import ResendEmailSender

DESTINO = "estudiante@test.invalid"
REMITENTE = "avisos@test.invalid"


async def _encolar(sesiones, user_id, plantilla="password_changed", **datos):
    async with sesiones.begin() as db:
        return outbox.encolar_correo(db, user_id=user_id, destinatario=DESTINO, plantilla=plantilla, **datos)


async def _fila(sesiones, id_correo):
    async with sesiones() as db:
        return await db.get(EmailOutbox, id_correo)


async def test_encolar_participa_en_la_transaccion(sesiones, datos):
    async with sesiones() as db:
        id_correo = outbox.encolar_correo(
            db, user_id=datos.ana.id, destinatario=DESTINO, plantilla="password_changed",
        )
        await db.flush()
        assert await db.get(EmailOutbox, id_correo) is not None
        assert await _fila(sesiones, id_correo) is None
        await db.rollback()
    assert await _fila(sesiones, id_correo) is None


async def test_arranque_envia_otp_cifrado_y_limpia_el_payload(sesiones, datos, monkeypatch):
    id_correo = await _encolar(
        sesiones, datos.ana.id, "verify_email", codigo="246810", vence_en=datetime.now(UTC) + timedelta(minutes=10),
    )
    antes = await _fila(sesiones, id_correo)
    assert antes.status == "pending"
    assert DESTINO.encode() not in antes.to_ct
    assert b"246810" not in antes.payload_ct
    assert pii.revelar(antes.to_ct, aad=f"email_outbox.to_ct.{id_correo}") == DESTINO
    solicitudes = []

    def responder(solicitud):
        solicitudes.append(solicitud)
        return httpx.Response(200, json={"id": "correo-de-prueba"})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    monkeypatch.setattr(outbox.httpx, "AsyncClient", lambda: cliente)
    monkeypatch.setattr(settings, "resend_api_key", SecretStr("llave-de-prueba"))
    monkeypatch.setattr(settings, "email_from", REMITENTE)
    monkeypatch.setattr(settings, "tarea_inactividad_activa", False)
    monkeypatch.setattr(database, "SesionTareas", sesiones, raising=False)
    monkeypatch.setattr(main, "verificar_llaves", lambda: None)

    async with main.ciclo_de_vida(main.app), asyncio.timeout(5):
        while (fila := await _fila(sesiones, id_correo)).status != "sent":
            await asyncio.sleep(0.02)

    (solicitud,) = solicitudes
    assert cliente.is_closed
    assert str(solicitud.url) == "https://api.resend.com/emails"
    assert solicitud.headers["Authorization"] == "Bearer llave-de-prueba"
    assert solicitud.headers["Idempotency-Key"] == str(id_correo)
    cuerpo = json.loads(solicitud.content)
    assert cuerpo["to"] == [DESTINO]
    assert cuerpo["from"] == REMITENTE
    assert "246810" in cuerpo["text"] and "Vence" in cuerpo["text"]
    assert "<strong>246810</strong>" in cuerpo["html"]
    assert fila.attempts == 1 and fila.sent_at is not None
    assert fila.provider_message_id == "correo-de-prueba" and fila.payload_ct is None


async def test_reintentos_persisten_horario_y_se_detienen_en_el_quinto(sesiones, datos, monkeypatch):
    ahora = datetime(2026, 11, 26, 14, tzinfo=UTC)
    monkeypatch.setattr(outbox, "_ahora", lambda: ahora)
    id_correo = await _encolar(sesiones, datos.ana.id)
    solicitudes = []

    def responder(solicitud):
        solicitudes.append(solicitud)
        return httpx.Response(503, json={"message": DESTINO})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        sender = ResendEmailSender(cliente, "llave-de-prueba", REMITENTE)
        for intento, espera in enumerate((1, 5, 30, 30), start=1):
            assert await outbox.procesar_uno(sesiones, sender)
            fila = await _fila(sesiones, id_correo)
            assert (fila.status, fila.attempts, fila.last_error) == ("pending", intento, "http_503")
            assert fila.next_attempt_at == ahora + timedelta(minutes=espera)
            assert not await outbox.procesar_uno(sesiones, sender)
            ahora = fila.next_attempt_at

        assert await outbox.procesar_uno(sesiones, sender)
        assert not await outbox.procesar_uno(sesiones, sender)

    fila = await _fila(sesiones, id_correo)
    assert (fila.status, fila.attempts, fila.last_error) == ("failed", 5, "http_503")
    assert fila.payload_ct is None
    assert len(solicitudes) == 5
    assert {r.headers["Idempotency-Key"] for r in solicitudes} == {str(id_correo)}
    assert len({r.content for r in solicitudes}) == 1


async def test_recupera_un_envio_interrumpido_sin_compartir_reserva(sesiones, datos, monkeypatch):
    ahora = datetime(2026, 11, 26, 14, tzinfo=UTC)
    monkeypatch.setattr(outbox, "_ahora", lambda: ahora)
    id_correo = await _encolar(sesiones, datos.ana.id)
    sender = FakeEmailSender()
    trabajo = asyncio.create_task(outbox.procesar_uno(sesiones, sender))
    try:
        await asyncio.wait_for(sender.aceptado.wait(), timeout=3)
        fila = await _fila(sesiones, id_correo)
        assert (fila.status, fila.attempts) == ("sending", 1)
        assert not await outbox.procesar_uno(sesiones, sender)
    finally:
        trabajo.cancel()
        with suppress(asyncio.CancelledError):
            await trabajo

    ahora = fila.next_attempt_at
    assert await outbox.procesar_uno(sesiones, sender)
    assert not await outbox.procesar_uno(sesiones, sender)

    fila = await _fila(sesiones, id_correo)
    assert (fila.status, fila.attempts) == ("sent", 2)
    assert sender.intentos == [id_correo, id_correo]
    assert sender.entregados == {id_correo}


class FakeEmailSender:
    def __init__(self):
        self.aceptado = asyncio.Event()
        self.intentos = []
        self.entregados = set()

    async def enviar(self, correo, idempotencia):
        self.intentos.append(idempotencia)
        if idempotencia not in self.entregados:
            self.entregados.add(idempotencia)
            self.aceptado.set()
            await asyncio.Future()  # El proveedor lo aceptó, pero aún no se registró la respuesta.
        return "correo-de-prueba"


@pytest.mark.parametrize(("codigo_http", "vencido", "motivo", "intentos"), [
    (422, False, "http_422", 1),
    (200, True, "otp_vencido", 0),
])
async def test_correo_no_entregable_termina_sin_reintentos(sesiones, datos, codigo_http, vencido, motivo, intentos):
    id_correo = await _encolar(
        sesiones, datos.ana.id, "reset_password", codigo="246810",
        vence_en=datetime.now(UTC) + timedelta(minutes=-1 if vencido else 10),
    )
    solicitudes = []

    def responder(solicitud):
        solicitudes.append(solicitud)
        return httpx.Response(codigo_http, json={"message": DESTINO})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        sender = ResendEmailSender(cliente, "llave-de-prueba", REMITENTE)
        assert await outbox.procesar_uno(sesiones, sender)
        assert not await outbox.procesar_uno(sesiones, sender)
    fila = await _fila(sesiones, id_correo)
    assert (fila.status, fila.attempts, fila.last_error) == ("failed", intentos, motivo)
    assert fila.payload_ct is None and len(solicitudes) == intentos
