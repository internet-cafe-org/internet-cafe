"""Endpoints de autenticación web: registro, login, refresh y logout.

SEC-02 aporta ``/auth/register`` y ``/auth/login``; SEC-03a, ``/auth/refresh``
y ``/auth/logout``. El refresh token viaja solo en la cookie ``__Secure-rt``
(HttpOnly, Secure, SameSite=Strict, ``Path=/api/v1/auth``; SRS §12.2). El
access token se entrega en el cuerpo y el cliente lo guarda en memoria.
"""

import re
from functools import lru_cache
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import settings
from app.database import obtener_base_datos
from app.errors import AppError, ErrorCode
from app.jwt import create_access_token
from app.logger import obtener_logger
from app.models import AuditActorType, User, UserRole, UserStatus
from app.security import limites
from app.services import pii, refresh_tokens
from app.services.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = obtener_logger("auth")

COOKIE_NAME = "__Secure-rt"
COOKIE_PATH = "/api/v1/auth"
TOKEN_TYPE = "Bearer"

# Forma mínima de un correo: algo@dominio.tld, sin espacios. La validación real
# es que el dominio esté permitido (ALLOWED_EMAIL_DOMAINS).
_PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _registrar_evento(evento: str, *, resultado: str, user_id: uuid.UUID | None = None,
                      motivo: str | None = None) -> None:
    """Escribe un evento de autenticación en el log JSON, sin datos personales.

    Args:
        evento: Nombre del evento (p. ej. ``auth.login``).
        resultado: ``ok`` o ``rechazado``.
        user_id: Id interno del usuario, si se conoce.
        motivo: Motivo del rechazo, si lo hubo.
    """
    datos: dict[str, str] = {"evento": evento, "resultado": resultado}
    if user_id is not None:
        datos["user_id"] = str(user_id)
    if motivo:
        datos["motivo"] = motivo
    logger.info(evento, extra={"datos": datos})


# ---------------------------------------------------------------- esquemas


def _normalizar_correo(valor: str) -> str:
    """Valida la forma del correo y el dominio permitido.

    Args:
        valor: Correo tal como llegó en la petición.

    Returns:
        El correo recortado y en minúsculas.

    Raises:
        ValueError: Si no tiene forma de correo o su dominio no está permitido.
            Pydantic lo convierte en un 422 ``VALIDATION_ERROR``.
    """
    correo = valor.strip().lower()
    if not _PATRON_CORREO.fullmatch(correo):
        raise ValueError("El correo no es válido.")
    return correo


class RegistroEntrada(BaseModel):
    """Cuerpo de ``POST /auth/register`` (RF-AUT-01)."""

    # La contraseña no se recorta: los espacios son parte de ella.
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    student_code: str = Field(min_length=4, max_length=20, pattern=r"^[0-9A-Za-z-]+$")
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    privacy_consent: Literal[True]

    @field_validator("student_code", "full_name", mode="before")
    @classmethod
    def _recortar(cls, valor: object) -> object:
        """Quita los espacios de los extremos del código y del nombre.

        Args:
            valor: Valor recibido.

        Returns:
            El texto recortado, o el valor sin cambios si no es texto.
        """
        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("email")
    @classmethod
    def _correo_institucional(cls, valor: str) -> str:
        """Normaliza el correo y exige un dominio permitido.

        Args:
            valor: Correo recibido.

        Returns:
            El correo normalizado.

        Raises:
            ValueError: Si el correo no es válido o su dominio no está permitido.
        """
        correo = _normalizar_correo(valor)
        dominios = settings.dominios_correo_permitidos
        if dominios and correo.rsplit("@", 1)[1] not in dominios:
            raise ValueError("El dominio del correo no está permitido.")
        return correo


class LoginEntrada(BaseModel):
    """Cuerpo de ``POST /auth/login`` (RF-AUT-05)."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UsuarioSesion(BaseModel):
    """Datos mínimos del usuario que la web guarda en Pinia."""

    id: uuid.UUID
    full_name: str
    role: UserRole


class TokenAcceso(BaseModel):
    """Respuesta de ``/auth/refresh``."""

    access_token: str
    token_type: Literal["Bearer"] = TOKEN_TYPE
    expires_in: int


class LoginSalida(TokenAcceso):
    """Respuesta de ``/auth/login``."""

    user: UsuarioSesion


# ---------------------------------------------------------------- cookie y origen


def poner_cookie_refresh(response: Response, token: str) -> None:
    """Pone la cookie ``__Secure-rt`` con el refresh token.

    Args:
        response: Respuesta a la que se agrega el ``Set-Cookie``.
        token: Refresh token opaco recién emitido.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def borrar_cookie_refresh(response: Response) -> None:
    """Borra la cookie ``__Secure-rt`` del navegador.

    Args:
        response: Respuesta a la que se agrega el ``Set-Cookie`` de borrado.
    """
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _cabecera_borrado() -> dict[str, str]:
    """Arma el ``Set-Cookie`` de borrado para adjuntarlo a un error.

    Returns:
        Diccionario con la cabecera ``set-cookie`` que borra la cookie.
    """
    temporal = Response()
    borrar_cookie_refresh(temporal)
    return {"set-cookie": temporal.headers["set-cookie"]}


@lru_cache(maxsize=4)
def _patron_preview(regex: str) -> re.Pattern[str]:
    """Compila una sola vez la expresión de los previews de Vercel.

    Args:
        regex: Valor de ``ORIGEN_PREVIEW_REGEX``.

    Returns:
        La expresión compilada.
    """
    return re.compile(regex)


def origen_permitido(origin: str) -> bool:
    """Decide si un ``Origin`` puede usar los endpoints con cookie (SEC-03b).

    Se permiten ``FRONTEND_BASE_URL``, los orígenes de ``ALLOWED_ORIGIN`` y,
    solo con ``APP_ENV=dev``, los previews que cumplan ``ORIGEN_PREVIEW_REGEX``.

    Args:
        origin: Valor de la cabecera ``Origin``.

    Returns:
        ``True`` si el origen está permitido.
    """
    origen = origin.rstrip("/")
    permitidos = {settings.frontend_base_url.rstrip("/")}
    if settings.allowed_origin:
        permitidos |= {o.strip().rstrip("/") for o in settings.allowed_origin.split(",") if o.strip()}
    if origen in permitidos:
        return True
    regex = settings.origen_preview_regex
    return bool(settings.app_env == "dev" and regex and _patron_preview(regex).fullmatch(origen))


def verificar_origen(origin: str | None = Header(default=None)) -> None:
    """Defensa CSRF adicional a SameSite en los endpoints con cookie (SEC-03b).

    Los navegadores siempre envían ``Origin`` en un ``POST`` con ``fetch``;
    si llega, debe estar permitido. Sin cabecera (clientes que no son un
    navegador) no hay riesgo de CSRF y se deja pasar.

    Args:
        origin: Cabecera ``Origin`` de la petición, si existe.

    Raises:
        AppError: ``FORBIDDEN`` si el origen no está permitido.
    """
    if origin and not origen_permitido(origin):
        _registrar_evento("auth.origen", resultado="rechazado", motivo="origen_no_permitido")
        raise AppError(ErrorCode.FORBIDDEN)


def _expira_en() -> int:
    """Devuelve la vida del access token en segundos.

    Returns:
        Segundos de ``JWT_ACCESS_TOKEN_EXPIRE_MINUTES``.
    """
    return settings.jwt_access_token_expire_minutes * 60


async def _contar_intento_fallido(db: AsyncSession, usuario: User, ahora: datetime) -> None:
    """Suma un intento fallido y bloquea la cuenta al llegar al máximo (SEC-09).

    Tras ``LOGIN_MAX_INTENTOS`` fallos seguidos la cuenta queda bloqueada
    ``LOGIN_BLOQUEO_MINUTOS`` y el contador vuelve a cero. Confirma la
    transacción, porque la petición termina en error.

    Args:
        db: Sesión de base de datos.
        usuario: Usuario que falló la contraseña.
        ahora: Hora actual.
    """
    usuario.failed_login_count = (usuario.failed_login_count or 0) + 1
    if usuario.failed_login_count >= settings.login_max_intentos:
        usuario.locked_until = ahora + timedelta(minutes=settings.login_bloqueo_minutos)
        usuario.failed_login_count = 0
        await audit(db, AuditActorType.system, "auth.lockout", target_type="user", target_id=usuario.id)
        _registrar_evento("auth.lockout", resultado="ok", user_id=usuario.id)
    await db.commit()


@cache
def _hash_senuelo() -> str:
    """Hash Argon2id de una contraseña que nadie usa.

    Se verifica contra él cuando el correo no existe, para que el login tarde
    lo mismo exista o no la cuenta (RF-AUT-05: no revelar si el correo existe).

    Returns:
        Hash Argon2id fijo durante la vida del proceso.
    """
    return hash_password(uuid.uuid4().hex)


# ---------------------------------------------------------------- endpoints


@router.post("/register", status_code=202, response_class=Response)
async def registrar(
    datos: RegistroEntrada,
    request: Request,
    db: AsyncSession = Depends(obtener_base_datos),
) -> Response:
    """Crea la cuenta de un estudiante y responde siempre 202 (SEC-02).

    Si el correo o el código estudiantil ya existen no se crea otra cuenta y la
    respuesta es la misma, para no revelar cuál existe (RF-AUT-01). La
    contraseña se calcula igual en ambos casos para no delatarlo por el tiempo.

    Args:
        datos: Cuerpo validado de la petición.
        request: Petición, para el rate limit por IP.
        db: Sesión de base de datos.

    Returns:
        Respuesta 202 sin cuerpo.

    Raises:
        AppError: 429 ``RATE_LIMITED`` si se superó el límite (SEC-09).
    """
    limites.limitar(request, "auth.register", cuenta=datos.email)
    password_hash = hash_password(datos.password)
    email_bidx = pii.indice_ciego(datos.email)
    codigo_bidx = pii.indice_ciego(datos.student_code)

    existente = await db.scalar(
        select(User.id).where(
            or_(User.email_bidx == email_bidx, User.student_code_bidx == codigo_bidx)
        )
    )
    if existente is None:
        ahora = datetime.now(UTC)
        activa = not settings.require_email_verification
        usuario = User(
            email_ct=pii.proteger(datos.email),
            email_bidx=email_bidx,
            student_code_ct=pii.proteger(datos.student_code),
            student_code_bidx=codigo_bidx,
            full_name_ct=pii.proteger(datos.full_name),
            password_hash=password_hash,
            role=UserRole.student,
            status=UserStatus.active if activa else UserStatus.pending_verification,
            privacy_consent_at=ahora,
        )
        db.add(usuario)
        try:
            await db.flush()
            await audit(
                db,
                AuditActorType.user,
                "auth.register",
                actor_id=usuario.id,
                target_type="user",
                target_id=usuario.id,
            )
            await db.commit()
            _registrar_evento("auth.register", resultado="ok", user_id=usuario.id)
        except IntegrityError:
            # Carrera con otro registro del mismo correo o código: misma respuesta.
            await db.rollback()
            _registrar_evento("auth.register", resultado="rechazado", motivo="duplicado")
    else:
        _registrar_evento("auth.register", resultado="rechazado", motivo="duplicado")

    return Response(status_code=202)


@router.post("/login", response_model=LoginSalida)
async def iniciar_sesion(
    datos: LoginEntrada,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(obtener_base_datos),
) -> LoginSalida:
    """Valida correo y contraseña, emite el access token y pone la cookie (SEC-02).

    Args:
        datos: Cuerpo validado de la petición.
        request: Petición, para leer el ``User-Agent``.
        response: Respuesta, para poner la cookie y ``Cache-Control``.
        db: Sesión de base de datos.

    Returns:
        Access token, su vida en segundos y los datos mínimos del usuario.

    Raises:
        AppError: ``AUTH_INVALID_CREDENTIALS`` si el correo no existe, la
            contraseña no coincide o la cuenta está bloqueada;
            ``AUTH_ACCOUNT_LOCKED`` si está en bloqueo temporal (SEC-09);
            ``AUTH_EMAIL_NOT_VERIFIED`` si la cuenta no se ha verificado;
            ``RATE_LIMITED`` si se superó el límite de peticiones.
    """
    correo = datos.email.strip().lower()
    limites.limitar(request, "auth.login", cuenta=correo)
    usuario = None
    if _PATRON_CORREO.fullmatch(correo):
        usuario = await db.scalar(select(User).where(User.email_bidx == pii.indice_ciego(correo)))

    if usuario is None:
        verify_password(datos.password, _hash_senuelo())
        _registrar_evento("auth.login", resultado="rechazado", motivo="cuenta_inexistente")
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)

    ahora = datetime.now(UTC)
    rechazo: tuple[str, ErrorCode] | None = None
    if usuario.locked_until is not None and usuario.locked_until > ahora:
        rechazo = ("bloqueo_temporal", ErrorCode.AUTH_ACCOUNT_LOCKED)
    elif not verify_password(datos.password, usuario.password_hash):
        rechazo = ("contrasena_incorrecta", ErrorCode.AUTH_INVALID_CREDENTIALS)
        await _contar_intento_fallido(db, usuario, ahora)
    elif usuario.status == UserStatus.blocked:
        rechazo = ("cuenta_bloqueada", ErrorCode.AUTH_INVALID_CREDENTIALS)
    elif usuario.status == UserStatus.pending_verification:
        rechazo = ("correo_sin_verificar", ErrorCode.AUTH_EMAIL_NOT_VERIFIED)
    if rechazo is not None:
        _registrar_evento("auth.login", resultado="rechazado", user_id=usuario.id, motivo=rechazo[0])
        raise AppError(rechazo[1])

    acceso = create_access_token(subject=str(usuario.id), role=usuario.role.value)
    refresh = await refresh_tokens.emitir(db, usuario.id, request.headers.get("user-agent"))
    usuario.last_login_at = ahora
    usuario.failed_login_count = 0
    usuario.locked_until = None
    await audit(db, AuditActorType.user, "auth.login", actor_id=usuario.id)
    await db.commit()
    _registrar_evento("auth.login", resultado="ok", user_id=usuario.id)

    poner_cookie_refresh(response, refresh)
    response.headers["Cache-Control"] = "no-store"
    return LoginSalida(
        access_token=acceso,
        expires_in=_expira_en(),
        user=UsuarioSesion(
            id=usuario.id,
            full_name=pii.revelar(usuario.full_name_ct),
            role=usuario.role,
        ),
    )


@router.post("/refresh", response_model=TokenAcceso, dependencies=[Depends(verificar_origen)])
async def refrescar(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(obtener_base_datos),
) -> TokenAcceso:
    """Rota el refresh token y devuelve un access token nuevo (SEC-03a).

    Args:
        request: Petición, para leer el ``User-Agent``.
        response: Respuesta, para poner la cookie nueva y ``Cache-Control``.
        refresh_token: Valor de la cookie ``__Secure-rt``.
        db: Sesión de base de datos.

    Returns:
        Access token nuevo y su vida en segundos.

    Raises:
        AppError: ``AUTH_INVALID_CREDENTIALS`` si no hay cookie o el token es
            desconocido, revocado o reutilizado; ``AUTH_TOKEN_EXPIRED`` si
            venció. En ambos casos se borra la cookie.
    """
    if not refresh_token:
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)
    # El refresh solo se limita por su token: no cuenta para el límite por IP (SEC-09).
    limites.limitar(request, "auth.refresh", cuenta=refresh_token, contar_ip=False)

    try:
        rotacion = await refresh_tokens.rotar(
            db, refresh_token, request.headers.get("user-agent")
        )
    except refresh_tokens.RefreshExpirado:
        _registrar_evento("auth.refresh", resultado="rechazado", motivo="vencido")
        raise AppError(ErrorCode.AUTH_TOKEN_EXPIRED, headers=_cabecera_borrado()) from None
    except refresh_tokens.RefreshInvalido as exc:
        # El motivo ("reutilizado" indica posible robo) viene del servicio, sin el token.
        _registrar_evento("auth.refresh", resultado="rechazado", motivo=str(exc) or "invalido")
        raise AppError(
            ErrorCode.AUTH_INVALID_CREDENTIALS, headers=_cabecera_borrado()
        ) from None

    acceso = create_access_token(
        subject=str(rotacion.user_id), role=str(rotacion.role.value)
    )
    poner_cookie_refresh(response, rotacion.token)
    response.headers["Cache-Control"] = "no-store"
    return TokenAcceso(access_token=acceso, expires_in=_expira_en())


@router.post(
    "/logout", status_code=204, dependencies=[Depends(verificar_origen)]
)
async def cerrar_sesion(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: AsyncSession = Depends(obtener_base_datos),
) -> None:
    """Revoca la familia del refresh token y borra la cookie (SEC-03a).

    Es idempotente: responde 204 aunque no haya cookie o el token no exista.

    Args:
        request: Petición, para el rate limit por IP.
        response: Respuesta, para borrar la cookie.
        refresh_token: Valor de la cookie ``__Secure-rt``.
        db: Sesión de base de datos.

    Raises:
        AppError: 429 ``RATE_LIMITED`` si se superó el límite por IP.
    """
    limites.limitar(request, "auth.logout")
    if refresh_token:
        await refresh_tokens.revocar(db, refresh_token)
    borrar_cookie_refresh(response)
