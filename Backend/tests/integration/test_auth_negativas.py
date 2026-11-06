"""QA-04: pruebas negativas de autenticación sobre la API real (/api/v1).

Cubre lo que pide la tarea: credenciales inválidas, token vencido o revocado y cierre
de sesión. El refresh vencido, el reuso de un token revocado y el logout básico ya los
cubre test_refresh_tokens.py (SEC-03a); aquí se agregan los casos que faltaban y las
pruebas del access token en una ruta protegida (/api/v1/me).

Cada prueba comprueba el código de error del contrato (AUTH_*), no solo el estado HTTP.
"""

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.routers.auth import COOKIE_NAME
from app.services import refresh_tokens

API = "/api/v1"


def _par_de_claves() -> tuple[str, str]:
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
    return privada, publica


@pytest.fixture
def claves(monkeypatch) -> str:
    """Claves ES256 efímeras para la API; devuelve la privada con la que firma el servidor."""
    privada, publica = _par_de_claves()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    return privada


@pytest.fixture
async def cliente(sesiones, claves):
    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _refresh_con_cookie(cliente, token: str):
    cliente.cookies.clear()
    return await cliente.post(
        f"{API}/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={token}"}
    )


# ---------------------------------------------------------------- Credenciales inválidas


async def test_me_sin_token(cliente, datos):
    resp = await cliente.get(f"{API}/me")

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_me_con_token_basura(cliente, datos):
    resp = await cliente.get(f"{API}/me", headers=_bearer("esto-no-es-un-jwt"))

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_me_con_esquema_distinto_a_bearer(cliente, datos):
    resp = await cliente.get(f"{API}/me", headers={"Authorization": "Basic YTpi"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_me_con_token_firmado_por_otra_clave(cliente, datos):
    """Un token bien formado pero firmado con una clave ajena no debe aceptarse."""
    otra_privada, _ = _par_de_claves()
    falso = create_access_token(
        subject=str(datos.ana.id), role="student", private_key=otra_privada
    )

    resp = await cliente.get(f"{API}/me", headers=_bearer(falso))

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_refresh_con_cookie_desconocida(cliente, datos):
    """Un refresh token que nunca se emitió se rechaza como credencial inválida."""
    resp = await _refresh_con_cookie(cliente, "refresh-token-que-no-existe")

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


# ------------------------------------------------------------ Token vencido o revocado


async def test_me_con_access_token_vencido(cliente, claves, datos):
    vencido = create_access_token(
        subject=str(datos.ana.id),
        role="student",
        private_key=claves,
        expires_delta=timedelta(seconds=-60),
    )

    resp = await cliente.get(f"{API}/me", headers=_bearer(vencido))

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_TOKEN_EXPIRED"


async def test_me_con_access_token_valido_responde_200(cliente, claves, datos):
    """Control positivo: confirma que los rechazos de arriba se deben al token."""
    valido = create_access_token(
        subject=str(datos.ana.id), role="student", private_key=claves
    )

    resp = await cliente.get(f"{API}/me", headers=_bearer(valido))

    assert resp.status_code == 200


async def test_refresh_revocado_responde_credencial_invalida(cliente, sesiones, datos):
    async with sesiones() as db:
        token = await refresh_tokens.emitir(db, datos.ana.id, "pytest")
        await db.commit()
    salida = await cliente.post(
        f"{API}/auth/logout", headers={"Cookie": f"{COOKIE_NAME}={token}"}
    )
    assert salida.status_code == 204

    resp = await _refresh_con_cookie(cliente, token)

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


# ------------------------------------------------------------------- Cerrar sesión


async def test_logout_con_cookie_desconocida_no_falla(cliente, datos):
    """El logout es idempotente: aunque la cookie sea basura responde 204."""
    cliente.cookies.clear()
    resp = await cliente.post(
        f"{API}/auth/logout", headers={"Cookie": f"{COOKIE_NAME}=cookie-falsa"}
    )

    assert resp.status_code == 204
    assert "max-age=0" in resp.headers["set-cookie"].lower()


# ----------------------------------------------------------------- Registro duplicado


@pytest.mark.skip(
    reason="POST /api/v1/registro está en openapi.yaml pero aún no existe en el "
    "backend (SEC-02, #102). Quitar este skip cuando se fusione y comprobar el "
    "código de error del contrato para correo duplicado."
)
async def test_registro_con_correo_existente(cliente, datos):
    pass