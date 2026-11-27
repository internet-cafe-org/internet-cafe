"""OTP de 6 dígitos para verificar correo y recuperar contraseña (ST-SEC-01).

Solo se guarda el HMAC-SHA256 del código (con ``OTP_HMAC_KEY``), nunca el código.
Vigencia de 10 minutos y máximo 5 intentos (SRS RF-AUT-02). También gestiona la
emisión, invalidación, consumo atómico y encolado en ``email_outbox``.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import constant_time_compare, hmac_sha256_digest
from app.models import EmailCode, EmailCodePurpose, User
from app.services import outbox

OTP_DIGITOS = 6
OTP_VIGENCIA = timedelta(minutes=10)
OTP_MAX_INTENTOS = 5

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
    plantilla: outbox.Plantilla = (
        "verify_email" if proposito == EmailCodePurpose.verify_email else "reset_password"
    )
    outbox.encolar_correo(
        db,
        user_id=usuario.id,
        destinatario=destinatario,
        plantilla=plantilla,
        codigo=codigo,
        vence_en=expira,
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
