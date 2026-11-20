"""Pruebas de integración de ``/auth/register`` y ``/auth/login`` (SEC-02, #102).

Cubren el camino feliz (registro, login, cookie y renovación con la cookie del
login) y los rechazos que fija el contrato v0.2.1. Los datos son ficticios.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import verify_access_token
from app.main import app
from app.models import AuditLog, RefreshToken, User, UserRole, UserStatus
from app.routers.auth import COOKIE_NAME
from app.services import pii

RUTA = "/api/v1/auth"
CLAVE_INDICE = bytes(range(32)).hex()
CONTRASENA = "una contraseña larga"


def _registro(**cambios: object) -> dict:
    """Arma un cuerpo de registro válido con los cambios indicados.

    Args:
        **cambios: Campos que se sobrescriben o se agregan.

    Returns:
        Diccionario listo para enviar como JSON.
    """
    cuerpo = {
        "email": "estudiante.prueba@test.invalid",
        "student_code": "2026000001",
        "full_name": "Estudiante De Prueba",
        "password": CONTRASENA,
        "privacy_consent": True,
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.fixture
def claves(monkeypatch) -> None:
    """Configura llaves ES256 efímeras y la llave del índice ciego."""
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    publica = (
        clave.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    monkeypatch.setattr(settings, "blind_index_key", CLAVE_INDICE)
    monkeypatch.setattr(settings, "allowed_email_domains", "")
    monkeypatch.setattr(settings, "require_email_verification", False)


@pytest.fixture
async def cliente(sesiones, claves):
    """Cliente HTTP contra la app, con la base de pruebas inyectada."""

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _usuarios(sesiones) -> list[User]:
    """Devuelve todos los usuarios de la base de pruebas.

    Args:
        sesiones: Fábrica de sesiones de la base de pruebas.

    Returns:
        Lista de usuarios.
    """
    async with sesiones() as db:
        return list((await db.scalars(select(User))).all())


# ---------------------------------------------------------------- registro


async def test_registro_crea_cuenta_activa_y_responde_202(cliente, sesiones):
    resp = await cliente.post(f"{RUTA}/register", json=_registro())

    assert resp.status_code == 202
    assert resp.content == b""
    [usuario] = await _usuarios(sesiones)
    assert usuario.status == UserStatus.active
    assert usuario.role == UserRole.student
    assert usuario.password_hash.startswith("$argon2id$")
    assert usuario.email_bidx == pii.indice_ciego("estudiante.prueba@test.invalid")
    assert usuario.student_code_bidx == pii.indice_ciego("2026000001")
    assert pii.revelar(usuario.full_name_ct) == "Estudiante De Prueba"
    assert usuario.privacy_consent_at is not None
    async with sesiones() as db:
        acciones = (await db.scalars(select(AuditLog.action))).all()
    assert acciones == ["auth.register"]


async def test_registro_normaliza_el_correo(cliente, sesiones):
    resp = await cliente.post(
        f"{RUTA}/register", json=_registro(email="  Estudiante.Prueba@TEST.invalid ")
    )

    assert resp.status_code == 202
    [usuario] = await _usuarios(sesiones)
    assert pii.revelar(usuario.email_ct) == "estudiante.prueba@test.invalid"


async def test_registro_con_verificacion_deja_la_cuenta_pendiente(cliente, sesiones, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)

    resp = await cliente.post(f"{RUTA}/register", json=_registro())

    assert resp.status_code == 202
    [usuario] = await _usuarios(sesiones)
    assert usuario.status == UserStatus.pending_verification


@pytest.mark.parametrize(
    "cambios",
    [
        {"email": "Estudiante.Prueba@test.invalid", "student_code": "2026999999"},
        {"email": "otro.correo@test.invalid", "student_code": "2026000001"},
    ],
    ids=["mismo-correo", "mismo-codigo"],
)
async def test_registro_duplicado_responde_202_sin_crear_otra_cuenta(cliente, sesiones, cambios):
    primero = await cliente.post(f"{RUTA}/register", json=_registro())
    segundo = await cliente.post(f"{RUTA}/register", json=_registro(**cambios))

    assert primero.status_code == segundo.status_code == 202
    assert segundo.content == primero.content
    assert len(await _usuarios(sesiones)) == 1


@pytest.mark.parametrize(
    "cambios",
    [
        {"password": "corta"},
        {"password": "x" * 129},
        {"privacy_consent": False},
        {"email": "sin-arroba"},
        {"student_code": "con espacios"},
        {"full_name": " "},
        {"role": "admin"},
    ],
    ids=["clave-corta", "clave-larga", "sin-consentimiento", "correo-invalido",
         "codigo-invalido", "nombre-vacio", "campo-desconocido"],
)
async def test_registro_invalido_responde_422(cliente, sesiones, cambios):
    resp = await cliente.post(f"{RUTA}/register", json=_registro(**cambios))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert CONTRASENA not in resp.text
    assert await _usuarios(sesiones) == []


async def test_registro_rechaza_dominio_no_permitido(cliente, sesiones, monkeypatch):
    monkeypatch.setattr(settings, "allowed_email_domains", "universidad.test, @otra.test")

    rechazado = await cliente.post(f"{RUTA}/register", json=_registro())
    aceptado = await cliente.post(
        f"{RUTA}/register", json=_registro(email="ana@otra.test", student_code="2026000002")
    )

    assert rechazado.status_code == 422
    assert rechazado.json()["code"] == "VALIDATION_ERROR"
    assert aceptado.status_code == 202
    assert len(await _usuarios(sesiones)) == 1


# ---------------------------------------------------------------- login


async def test_login_emite_access_token_y_cookie(cliente, sesiones):
    await cliente.post(f"{RUTA}/register", json=_registro())

    resp = await cliente.post(
        f"{RUTA}/login", json={"email": "Estudiante.Prueba@test.invalid", "password": CONTRASENA}
    )

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["token_type"] == "Bearer"
    assert cuerpo["expires_in"] == settings.jwt_access_token_expire_minutes * 60
    assert cuerpo["user"]["full_name"] == "Estudiante De Prueba"
    assert cuerpo["user"]["role"] == "student"
    assert "password" not in resp.text and "refresh" not in cuerpo

    claims = verify_access_token(cuerpo["access_token"])
    assert claims["sub"] == cuerpo["user"]["id"]
    assert claims["role"] == "student"
    assert claims["aud"] == "web"

    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert atributo.lower() in cookie.lower()
    assert resp.headers["cache-control"] == "no-store"

    async with sesiones() as db:
        assert await db.scalar(select(func.count()).select_from(RefreshToken)) == 1
        usuario = await db.scalar(select(User))
        assert usuario.last_login_at is not None


async def test_la_cookie_del_login_sirve_para_renovar(cliente):
    await cliente.post(f"{RUTA}/register", json=_registro())
    login = await cliente.post(
        f"{RUTA}/login", json={"email": "estudiante.prueba@test.invalid", "password": CONTRASENA}
    )
    assert login.status_code == 200

    resp = await cliente.post(f"{RUTA}/refresh")

    assert resp.status_code == 200
    assert resp.json()["token_type"] == "Bearer"
    assert verify_access_token(resp.json()["access_token"])["sub"] == login.json()["user"]["id"]


@pytest.mark.parametrize(
    "credenciales",
    [
        {"email": "estudiante.prueba@test.invalid", "password": "otra contraseña larga"},
        {"email": "nadie@test.invalid", "password": CONTRASENA},
        {"email": "sin-arroba", "password": CONTRASENA},
    ],
    ids=["clave-incorrecta", "correo-inexistente", "correo-malformado"],
)
async def test_login_con_credenciales_invalidas_responde_401(cliente, credenciales):
    await cliente.post(f"{RUTA}/register", json=_registro())

    resp = await cliente.post(f"{RUTA}/login", json=credenciales)

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert "set-cookie" not in resp.headers


async def test_login_de_cuenta_bloqueada_no_revela_el_bloqueo(cliente, sesiones):
    await cliente.post(f"{RUTA}/register", json=_registro())
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        usuario.status = UserStatus.blocked
        await db.commit()

    resp = await cliente.post(
        f"{RUTA}/login", json={"email": "estudiante.prueba@test.invalid", "password": CONTRASENA}
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_login_de_cuenta_sin_verificar_responde_403(cliente, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)
    await cliente.post(f"{RUTA}/register", json=_registro())

    resp = await cliente.post(
        f"{RUTA}/login", json={"email": "estudiante.prueba@test.invalid", "password": CONTRASENA}
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "AUTH_EMAIL_NOT_VERIFIED"


async def test_login_rechaza_campos_desconocidos(cliente):
    resp = await cliente.post(
        f"{RUTA}/login",
        json={"email": "estudiante.prueba@test.invalid", "password": CONTRASENA, "role": "admin"},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
