"""OTP de 6 dígitos para verificar correo y recuperar contraseña (ST-SEC-01).

Solo se guarda el HMAC-SHA256 del código (con ``OTP_HMAC_KEY``), nunca el código.
Vigencia de 10 minutos y máximo 5 intentos (SRS RF-AUT-02). También gestiona la
emisión, invalidación, consumo atómico y encolado en ``email_outbox``.
"""

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import constant_time_compare, hmac_sha256_digest
from app.models import EmailCode, EmailCodePurpose, EmailOutbox, User
from app.services import pii

OTP_DIGITOS = 6
OTP_VIGENCIA = timedelta(minutes=10)
OTP_MAX_INTENTOS = 5

PlantillaCorreo = Literal["verify_email", "reset_password", "password_changed"]

_ASUNTOS: dict[PlantillaCorreo, str] = {
    "verify_email": "Verifica tu correo de Internet Café",
    "reset_password": "Recupera tu contraseña de Internet Café",
    "password_changed": "Tu contraseña de Internet Café cambió",
}
_TEXTO_AVISO_CLAVE = (
    "La contraseña de tu cuenta de Internet Café se cambió. "
    "Si no lo solicitaste, contacta a soporte."
)


class OtpError(Exception):
    """Error base en la validación o consumo de un código OTP."""


class OtpInvalidoError(OtpError):
    """El código no existe o no coincide con el HMAC guardado."""


class OtpYaUsadoError(OtpError):
    """El código ya fue consumido previamente."""


class OtpExpiradoError(OtpError):
    """El código superó su ventana de vigencia de 10 minutos."""


class OtpIntentosAgotadosError(OtpError):
    """El código alcanzó el máximo de 5 intentos fallidos."""


def generar_codigo() -> str:
    """Genera un código de 6 dígitos con ceros a la izquierda usando ``secrets``.

    Returns:
        Cadena numérica de 6 dígitos.
    """
    return f"{secrets.randbelow(10**OTP_DIGITOS):0{OTP_DIGITOS}d}"


def _clave() -> str:
    """Obtiene la llave HMAC configurada para los códigos OTP.

    Returns:
        Valor de ``OTP_HMAC_KEY``.

    Raises:
        ValueError: Si ``OTP_HMAC_KEY`` no está configurada.
    """
    if not settings.otp_hmac_key:
        raise ValueError("OTP_HMAC_KEY no esta configurada.")
    return settings.otp_hmac_key


def hash_codigo(codigo: str, user_id: object, proposito: str) -> bytes:
    """Calcula el HMAC-SHA256 del código ligado al usuario y al propósito.

    Args:
        codigo: Código numérico de 6 dígitos.
        user_id: Identificador del usuario dueño del código.
        proposito: Propósito del código (``verify_email`` o ``reset_password``).

    Returns:
        Resumen binario HMAC-SHA256 de 32 bytes.
    """
    return hmac_sha256_digest(_clave(), f"{user_id}:{proposito}:{codigo}")


def vence_en(ahora: datetime) -> datetime:
    """Calcula la fecha de vencimiento de un código creado en ``ahora``.

    Args:
        ahora: Marca temporal de creación en UTC.

    Returns:
        Marca temporal de expiración (+10 minutos).
    """
    return ahora + OTP_VIGENCIA


def verificar(
    codigo: str,
    user_id: object,
    proposito: str,
    code_hash: bytes,
    intentos: int,
    expires_at: datetime,
    ahora: datetime,
) -> bool:
    """Valida el código contra su HMAC, intentos disponibles y expiración.

    Args:
        codigo: Código enviado por el usuario.
        user_id: Identificador del usuario.
        proposito: Propósito esperado del código.
        code_hash: HMAC guardado en base de datos.
        intentos: Intentos fallidos acumulados.
        expires_at: Fecha límite de vigencia.
        ahora: Hora actual del servidor.

    Returns:
        ``True`` si el código es correcto, vigente y con intentos disponibles.
    """
    if intentos >= OTP_MAX_INTENTOS or ahora >= expires_at:
        return False
    return constant_time_compare(hash_codigo(codigo, user_id, proposito), code_hash)


def _aad_outbox(id_correo: uuid.UUID, columna: str) -> str:
    """Construye el AAD de cifrado para una columna de ``email_outbox``.

    Args:
        id_correo: Identificador de la fila del outbox.
        columna: Nombre de la columna cifrada (``to_ct`` o ``payload_ct``).

    Returns:
        Cadena AAD ``email_outbox.<columna>.<id>``.
    """
    return f"email_outbox.{columna}.{id_correo}"


def _construir_payload_correo(
    plantilla: PlantillaCorreo,
    *,
    codigo: str | None = None,
    vence_en_dt: datetime | None = None,
) -> str:
    """Serializa el payload JSON esperado por el worker de ``email_outbox``.

    Args:
        plantilla: Nombre de la plantilla de correo.
        codigo: Código OTP de 6 dígitos cuando la plantilla lo requiere.
        vence_en_dt: Fecha de expiración del código con zona horaria.

    Returns:
        JSON serializado con asunto, texto, html y fecha de expiración.
    """
    asunto = _ASUNTOS[plantilla]
    if plantilla == "password_changed":
        texto = _TEXTO_AVISO_CLAVE
        html = f"<p>{_TEXTO_AVISO_CLAVE}</p>"
        vencimiento = None
    else:
        assert codigo is not None and vence_en_dt is not None
        vence_utc = vence_en_dt.astimezone(UTC)
        vence_fmt = vence_utc.strftime("%d/%m/%Y a las %H:%M UTC")
        texto = f"Tu código es {codigo}. Vence el {vence_fmt}."
        html = f"<p>Tu código es <strong>{codigo}</strong>. Vence el {vence_fmt}.</p>"
        vencimiento = vence_utc.isoformat()
    return json.dumps({"asunto": asunto, "texto": texto, "html": html, "vence_en": vencimiento})


def encolar_correo(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    destinatario: str,
    plantilla: PlantillaCorreo,
    codigo: str | None = None,
    vence_en_dt: datetime | None = None,
    ahora: datetime | None = None,
) -> uuid.UUID:
    """Agrega un correo cifrado en ``email_outbox`` dentro de la transacción actual.

    Args:
        db: Sesión de base de datos.
        user_id: Identificador del usuario destinatario.
        destinatario: Correo normalizado del destinatario.
        plantilla: Plantilla de correo (``verify_email``, ``reset_password`` o
            ``password_changed``).
        codigo: Código OTP de 6 dígitos si aplica.
        vence_en_dt: Expiración del OTP en UTC si aplica.
        ahora: Hora actual del servidor.

    Returns:
        Identificador de la fila creada en ``email_outbox``.
    """
    marca = ahora or datetime.now(UTC)
    id_correo = uuid.uuid4()
    payload = _construir_payload_correo(plantilla, codigo=codigo, vence_en_dt=vence_en_dt)
    db.add(
        EmailOutbox(
            id=id_correo,
            user_id=user_id,
            template=plantilla,
            to_ct=pii.proteger(destinatario, aad=_aad_outbox(id_correo, "to_ct")),
            payload_ct=pii.proteger(payload, aad=_aad_outbox(id_correo, "payload_ct")),
            created_at=marca,
            next_attempt_at=marca,
        )
    )
    return id_correo


async def emitir_otp(
    db: AsyncSession,
    *,
    usuario: User,
    destinatario: str,
    proposito: EmailCodePurpose,
    ahora: datetime | None = None,
) -> str:
    """Invalida códigos activos previos, crea un nuevo OTP y encola el correo.

    Args:
        db: Sesión de base de datos.
        usuario: Cuenta para la que se emite el código.
        destinatario: Correo normalizado donde se enviará el código.
        proposito: Propósito del OTP (``verify_email`` o ``reset_password``).
        ahora: Hora actual del servidor.

    Returns:
        Código OTP en claro recién generado (solo para pruebas o entrega inmediata
        al outbox cifrado; nunca debe registrarse en logs).
    """
    marca = ahora or datetime.now(UTC)
    await db.execute(
        update(EmailCode)
        .where(
            EmailCode.user_id == usuario.id,
            EmailCode.purpose == proposito,
            EmailCode.consumed_at.is_(None),
        )
        .values(consumed_at=marca)
    )
    codigo = generar_codigo()
    expira = vence_en(marca)
    db.add(
        EmailCode(
            user_id=usuario.id,
            purpose=proposito,
            code_hash=hash_codigo(codigo, usuario.id, proposito.value),
            attempts=0,
            expires_at=expira,
            created_at=marca,
        )
    )
    plantilla: PlantillaCorreo = (
        "verify_email" if proposito == EmailCodePurpose.verify_email else "reset_password"
    )
    encolar_correo(
        db,
        user_id=usuario.id,
        destinatario=destinatario,
        plantilla=plantilla,
        codigo=codigo,
        vence_en_dt=expira,
        ahora=marca,
    )
    return codigo


async def consumir_otp(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    proposito: EmailCodePurpose,
    codigo: str,
    ahora: datetime | None = None,
) -> EmailCode:
    """Valida de forma atómica el último OTP del usuario y lo marca como consumido.

    Args:
        db: Sesión de base de datos.
        user_id: Identificador del usuario.
        proposito: Propósito esperado del OTP.
        codigo: Código de 6 dígitos enviado por el cliente.
        ahora: Hora actual del servidor.

    Returns:
        Fila de ``EmailCode`` ya marcada como consumida.

    Raises:
        OtpInvalidoError: Si no hay código o los dígitos no coinciden (suma 1 intento).
        OtpYaUsadoError: Si el código más reciente ya estaba consumido.
        OtpIntentosAgotadosError: Si ya alcanzó los 5 intentos fallidos.
        OtpExpiradoError: Si superó los 10 minutos de vigencia.
    """
    marca = ahora or datetime.now(UTC)
    registro = await db.scalar(
        select(EmailCode)
        .where(EmailCode.user_id == user_id, EmailCode.purpose == proposito)
        .order_by(EmailCode.created_at.desc(), EmailCode.id.desc())
        .limit(1)
        .with_for_update()
    )
    if registro is None:
        raise OtpInvalidoError()
    if registro.consumed_at is not None:
        raise OtpYaUsadoError()
    if registro.attempts >= OTP_MAX_INTENTOS:
        raise OtpIntentosAgotadosError()
    if marca >= registro.expires_at:
        raise OtpExpiradoError()
    if not verificar(
        codigo,
        user_id,
        proposito.value,
        registro.code_hash,
        registro.attempts,
        registro.expires_at,
        marca,
    ):
        registro.attempts += 1
        await db.flush()
        raise OtpInvalidoError()

    registro.consumed_at = marca
    return registro
