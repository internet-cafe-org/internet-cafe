"""Catálogo de errores de la API en formato RFC 9457 (Problem Details).

Cada `ErrorCode` corresponde a una fila del catálogo del SRS §10.5 y trae su
status HTTP, título y detalle por defecto. Los routers lanzan `AppError` con
uno de estos códigos y `app.error_handlers` lo convierte en
`application/problem+json`.
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from app.config import settings

PROBLEM_MEDIA_TYPE = "application/problem+json"


@dataclass(frozen=True)
class ErrorSpec:
    """Status HTTP y textos por defecto de un código de error."""

    status: int
    title: str
    detail: str


class ErrorCode(StrEnum):
    """Códigos estables del catálogo de errores (SRS §10.5)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_EMAIL_NOT_VERIFIED = "AUTH_EMAIL_NOT_VERIFIED"
    AUTH_ACCOUNT_LOCKED = "AUTH_ACCOUNT_LOCKED"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"
    CHALLENGE_EXPIRED = "CHALLENGE_EXPIRED"
    CHALLENGE_ALREADY_USED = "CHALLENGE_ALREADY_USED"
    MACHINE_BUSY = "MACHINE_BUSY"
    MACHINE_DISABLED = "MACHINE_DISABLED"
    MACHINE_SIGNATURE_INVALID = "MACHINE_SIGNATURE_INVALID"
    MACHINE_CLOCK_SKEW = "MACHINE_CLOCK_SKEW"
    ENROLLMENT_CODE_INVALID = "ENROLLMENT_CODE_INVALID"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    # Genéricos para errores que no salen de un router (ruta inexistente, etc.)
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    @property
    def spec(self) -> ErrorSpec:
        return CATALOGO[self]

    @property
    def type_uri(self) -> str:
        """URI del tipo de problema, por ejemplo `.../challenge-expired`."""
        slug = self.value.lower().replace("_", "-")
        return f"{settings.errors_base_url.rstrip('/')}/{slug}"


CATALOGO: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.VALIDATION_ERROR: ErrorSpec(
        422, "Datos inválidos", "Corrige los campos indicados."
    ),
    ErrorCode.AUTH_INVALID_CREDENTIALS: ErrorSpec(
        401,
        "Credenciales incorrectas",
        "El correo o la contraseña no son correctos.",
    ),
    ErrorCode.AUTH_EMAIL_NOT_VERIFIED: ErrorSpec(
        403,
        "Cuenta sin verificar",
        "Ingresa el código de verificación o pide uno nuevo.",
    ),
    ErrorCode.AUTH_ACCOUNT_LOCKED: ErrorSpec(
        423,
        "Cuenta bloqueada temporalmente",
        "Demasiados intentos fallidos. Espera 15 minutos.",
    ),
    ErrorCode.AUTH_TOKEN_EXPIRED: ErrorSpec(
        401, "Sesión vencida", "El token de acceso venció."
    ),
    ErrorCode.FORBIDDEN: ErrorSpec(
        403, "Acceso denegado", "No tienes permisos para este recurso."
    ),
    ErrorCode.RATE_LIMITED: ErrorSpec(
        429,
        "Demasiadas peticiones",
        "Espera el tiempo indicado en Retry-After e inténtalo de nuevo.",
    ),
    ErrorCode.CHALLENGE_NOT_FOUND: ErrorSpec(
        404, "Código QR inválido", "Escanea el código QR del equipo."
    ),
    ErrorCode.CHALLENGE_EXPIRED: ErrorSpec(
        410, "El código QR expiró", "Escanea el código nuevo del equipo."
    ),
    ErrorCode.CHALLENGE_ALREADY_USED: ErrorSpec(
        409, "El código QR ya se usó", "Escanea el código nuevo del equipo."
    ),
    ErrorCode.MACHINE_BUSY: ErrorSpec(
        409,
        "Equipo ocupado",
        "El equipo ya tiene una sesión activa. Ciérrala y reintenta.",
    ),
    ErrorCode.MACHINE_DISABLED: ErrorSpec(
        403, "Equipo deshabilitado", "Contacta a soporte."
    ),
    ErrorCode.MACHINE_SIGNATURE_INVALID: ErrorSpec(
        401,
        "Firma del equipo inválida",
        "La firma de la petición falta, no es válida o está repetida.",
    ),
    ErrorCode.MACHINE_CLOCK_SKEW: ErrorSpec(
        401,
        "Reloj del equipo desfasado",
        "El reloj del equipo está fuera de la tolerancia permitida.",
    ),
    ErrorCode.ENROLLMENT_CODE_INVALID: ErrorSpec(
        401,
        "Código de enrolamiento inválido",
        "Pide un código nuevo al administrador.",
    ),
    ErrorCode.SESSION_NOT_FOUND: ErrorSpec(
        404, "Sesión no encontrada", "La sesión no existe o no es tuya."
    ),
    ErrorCode.BAD_REQUEST: ErrorSpec(
        400, "Petición inválida", "El servidor no pudo procesar la petición."
    ),
    ErrorCode.NOT_FOUND: ErrorSpec(
        404, "Recurso no encontrado", "La ruta solicitada no existe."
    ),
    ErrorCode.METHOD_NOT_ALLOWED: ErrorSpec(
        405, "Método no permitido", "La ruta no admite este método HTTP."
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        500,
        "Error interno",
        "Ocurrió un error inesperado. Inténtalo más tarde.",
    ),
}


class FieldError(BaseModel):
    """Un campo inválido de un 422. Nunca incluye el valor enviado."""

    field: str
    message: str


class ProblemDetail(BaseModel):
    """Cuerpo `application/problem+json` (RFC 9457) con `code` estable."""

    type: str
    title: str
    status: int
    code: ErrorCode
    detail: str
    instance: str
    errors: list[FieldError] | None = None


class AppError(Exception):
    """Error de dominio que la API devuelve como Problem Details."""

    def __init__(
        self,
        code: ErrorCode,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.detail = detail or code.spec.detail
        self.headers = headers
        super().__init__(code.value)
