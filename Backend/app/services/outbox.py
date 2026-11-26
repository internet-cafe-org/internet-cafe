"""Cola transaccional de correo y reintentos persistentes (ST-BE-01)."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.logger import obtener_logger
from app.models import EmailOutbox
from app.services import pii
from app.services.correo import Correo, EmailSender, ErrorEnvio, ResendEmailSender

Plantilla = Literal["verify_email", "reset_password", "password_changed"]
_ASUNTOS: dict[Plantilla, str] = {
    "verify_email": "Verifica tu correo de Internet Café",
    "reset_password": "Recupera tu contraseña de Internet Café",
    "password_changed": "Tu contraseña de Internet Café cambió",
}
_TEXTO_OTP = Template("Tu código es {{ codigo }}. Vence el {{ vence }}.", autoescape=False)
_HTML_OTP = Template("<p>Tu código es <strong>{{ codigo }}</strong>. Vence el {{ vence }}.</p>", autoescape=True)
_AVISO = "La contraseña de tu cuenta de Internet Café se cambió. Si no lo solicitaste, contacta a soporte."

_ESPERAS_MIN = (1, 5, 30, 30)
_MAX_INTENTOS = len(_ESPERAS_MIN) + 1
_RESERVA = timedelta(minutes=1)
_VENTANA_RESEND = timedelta(hours=24)
logger = obtener_logger("outbox")


def _ahora() -> datetime:
    return datetime.now(UTC)


def _aad(id_correo: UUID, columna: str) -> str:
    return f"email_outbox.{columna}.{id_correo}"


def encolar_correo(
    db: AsyncSession,
    *,
    user_id: UUID,
    destinatario: str,
    plantilla: Plantilla,
    codigo: str | None = None,
    vence_en: datetime | None = None,
) -> UUID:
    """Agrega el correo cifrado a la transacción del evento y devuelve su id."""
    asunto = _ASUNTOS[plantilla]
    if plantilla == "password_changed":
        texto, html = _AVISO, f"<p>{_AVISO}</p>"
        vencimiento = None
    else:
        if not codigo or len(codigo) != 6 or not codigo.isascii() or not codigo.isdecimal():
            raise ValueError("La plantilla de OTP requiere un código de seis dígitos.")
        if vence_en is None or vence_en.utcoffset() is None:
            raise ValueError("La plantilla de OTP requiere un vencimiento con zona horaria.")
        vence = vence_en.astimezone(UTC)
        variables = {"codigo": codigo, "vence": vence.strftime("%d/%m/%Y a las %H:%M UTC")}
        texto, html = _TEXTO_OTP.render(variables), _HTML_OTP.render(variables)
        vencimiento = vence.isoformat()

    id_correo = uuid4()
    ahora = _ahora()
    payload = json.dumps({"asunto": asunto, "texto": texto, "html": html, "vence_en": vencimiento})
    db.add(
        EmailOutbox(
            id=id_correo,
            user_id=user_id,
            template=plantilla,
            to_ct=pii.proteger(destinatario, aad=_aad(id_correo, "to_ct")),
            payload_ct=pii.proteger(payload, aad=_aad(id_correo, "payload_ct")),
            created_at=ahora,
            next_attempt_at=ahora,
        )
    )
    return id_correo


def _fallar(fila: EmailOutbox, motivo: str) -> None:
    fila.status = "failed"
    fila.last_error = motivo
    fila.payload_ct = None


async def procesar_uno(fabrica: async_sessionmaker[AsyncSession], sender: EmailSender) -> bool:
    """Procesa el siguiente correo disponible y devuelve si encontró trabajo."""
    ahora = _ahora()
    async with fabrica.begin() as db:
        fila = await db.scalar(
            select(EmailOutbox)
            .where(EmailOutbox.status.in_(("pending", "sending")), EmailOutbox.next_attempt_at <= ahora)
            .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if fila is None:
            return False
        if fila.attempts >= _MAX_INTENTOS:
            _fallar(fila, "intentos_agotados")
            return True
        if fila.attempts and ahora - fila.created_at >= _VENTANA_RESEND:
            _fallar(fila, "idempotencia_vencida")
            return True

        id_correo = fila.id
        try:
            datos = json.loads(pii.revelar(fila.payload_ct, aad=_aad(id_correo, "payload_ct")))
            vence = datos["vence_en"]
            if vence is not None and datetime.fromisoformat(vence) <= ahora:
                _fallar(fila, "otp_vencido")
                return True
            correo = Correo(
                pii.revelar(fila.to_ct, aad=_aad(id_correo, "to_ct")),
                datos["asunto"], datos["texto"], datos["html"],
            )
        except (pii.PiiError, ValueError, KeyError, TypeError):
            _fallar(fila, "payload_invalido")
            return True

        fila.status = "sending"
        fila.attempts += 1
        intento = fila.attempts
        fila.next_attempt_at = ahora + _RESERVA

    # El HTTP ocurre fuera de la transacción. Si el proceso cae, vence la reserva.
    error = None
    try:
        proveedor_id = await sender.enviar(correo, id_correo)
    except ErrorEnvio as exc:
        error = exc

    async with fabrica.begin() as db:
        fila = await db.scalar(
            select(EmailOutbox)
            .where(EmailOutbox.id == id_correo, EmailOutbox.status == "sending", EmailOutbox.attempts == intento)
            .with_for_update()
        )
        if fila is None:
            return True
        if error is None:
            fila.status = "sent"
            fila.provider_message_id = proveedor_id
            fila.sent_at = _ahora()
            fila.last_error = None
            fila.payload_ct = None
        elif error.reintentable and intento < _MAX_INTENTOS:
            fila.status = "pending"
            fila.last_error = str(error)
            fila.next_attempt_at = _ahora() + timedelta(minutes=_ESPERAS_MIN[intento - 1])
        else:
            _fallar(fila, str(error))
    return True


async def _trabajar(fabrica: async_sessionmaker[AsyncSession], sender: EmailSender) -> None:
    while True:
        try:
            for _ in range(10):
                if not await procesar_uno(fabrica, sender):
                    break
        except Exception:
            logger.warning("No se pudo completar un ciclo del outbox")
        await asyncio.sleep(30)


@asynccontextmanager
async def trabajador_configurado(fabrica: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """Mantiene el worker activo durante la vida de la API si Resend está configurado."""
    clave = settings.resend_api_key
    if not (clave and settings.email_from and settings.data_enc_keys):
        yield
        return

    async with httpx.AsyncClient() as cliente:
        sender = ResendEmailSender(cliente, clave.get_secret_value(), settings.email_from)
        tarea = asyncio.create_task(_trabajar(fabrica, sender))
        try:
            yield
        finally:
            tarea.cancel()
            with suppress(asyncio.CancelledError):
                await tarea
