"""OTP de 6 digitos para verificar correo y recuperar contrasena (ST-SEC-01).

Solo se guarda el HMAC-SHA256 del codigo (con OTP_HMAC_KEY), nunca el codigo.
Vigencia de 10 minutos y maximo 5 intentos (SRS RF-AUT-02).
"""

import secrets
from datetime import datetime, timedelta

from app.config import settings
from app.crypto import constant_time_compare, hmac_sha256_digest

OTP_DIGITOS = 6
OTP_VIGENCIA = timedelta(minutes=10)
OTP_MAX_INTENTOS = 5


def generar_codigo() -> str:
    """Codigo de 6 digitos con ceros a la izquierda, generado con secrets."""
    return f"{secrets.randbelow(10**OTP_DIGITOS):0{OTP_DIGITOS}d}"


def _clave() -> str:
    if not settings.otp_hmac_key:
        raise ValueError("OTP_HMAC_KEY no esta configurada.")
    return settings.otp_hmac_key


def hash_codigo(codigo: str, user_id: object, proposito: str) -> bytes:
    """HMAC del codigo ligado al usuario y al proposito."""
    return hmac_sha256_digest(_clave(), f"{user_id}:{proposito}:{codigo}")


def vence_en(ahora: datetime) -> datetime:
    """Fecha de vencimiento de un codigo creado en `ahora`."""
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
    """True si el codigo es correcto, vigente y con intentos disponibles."""
    if intentos >= OTP_MAX_INTENTOS or ahora >= expires_at:
        return False
    return constant_time_compare(hash_codigo(codigo, user_id, proposito), code_hash)