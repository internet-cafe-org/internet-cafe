"""Pruebas de integracion de /auth/refresh y /auth/logout (SEC-03a)."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import verify_access_token
from app.main import app
from app.models import RefreshToken
from app.routers.auth import COOKIE_NAME
from app.services import refresh_tokens

RUTA = "/api/v1/auth"


@pytest.fixture
def claves(monkeypatch):
    """Par de claves ES256 efimero para firmar y verificar el access token."""
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


async def _sesion(sesiones, user_id) -> str:
    """Simula lo que hara el login: crea un refresh token y lo confirma."""
    async with sesiones() as db:
        token = await refresh_tokens.emitir(db, user_id, "pytest")
        await db.commit()
    return token


async def _post(cliente, ruta, token=None, headers=None):
    cliente.cookies.clear()
    cabeceras = dict(headers or {})
    if token:
        cabeceras["Cookie"] = f"{COOKIE_NAME}={token}"
    return await cliente.post(f"{RUTA}{ruta}", headers=cabeceras)


def _cookie(resp) -> str:
    return resp.headers["set-cookie"].split(";")[0].split("=", 1)[1]


async def _fila(sesiones, token):
    async with sesiones() as db:
        return (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == refresh_tokens.hash_token(token)
                )
            )
        ).scalar_one_or_none()


async def test_refresh_rota_el_token(cliente, sesiones, datos):
    viejo = await _sesion(sesiones, datos.ana.id)
    resp = await _post(cliente, "/refresh", viejo)

    assert resp.status_code == 200
    nuevo = _cookie(resp)
    assert nuevo and nuevo != viejo

    claims = verify_access_token(resp.json()["access_token"])
    assert claims["sub"] == str(datos.ana.id)

    cab = resp.headers["set-cookie"].lower()
    assert "httponly" in cab
    assert "samesite=strict" in cab
    assert "path=/api/v1/auth" in cab

    fila_vieja = await _fila(sesiones, viejo)
    fila_nueva = await _fila(sesiones, nuevo)
    assert fila_vieja.revoked_at is not None
    assert fila_vieja.replaced_by == fila_nueva.id
    assert fila_nueva.family_id == fila_vieja.family_id


async def test_reutilizar_token_revoca_la_familia(cliente, sesiones, datos):
    viejo = await _sesion(sesiones, datos.ana.id)
    ok = await _post(cliente, "/refresh", viejo)
    nuevo = _cookie(ok)

    reuso = await _post(cliente, "/refresh", viejo)
    assert reuso.status_code == 401
    assert reuso.json()["code"] == "AUTH_INVALID_CREDENTIALS"

    # El token nuevo tambien queda inutilizable: se cerro toda la familia.
    despues = await _post(cliente, "/refresh", nuevo)
    assert despues.status_code == 401


async def test_refresh_sin_cookie(cliente, datos):
    resp = await _post(cliente, "/refresh")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_refresh_vencido(cliente, sesiones, datos):
    token = await _sesion(sesiones, datos.ana.id)
    async with sesiones() as db:
        await db.execute(
            update(RefreshToken).values(
                expires_at=datetime.now(UTC) - timedelta(hours=1)
            )
        )
        await db.commit()

    resp = await _post(cliente, "/refresh", token)
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_TOKEN_EXPIRED"


async def test_logout_revoca_y_limpia_la_cookie(cliente, sesiones, datos):
    token = await _sesion(sesiones, datos.ana.id)

    salida = await _post(cliente, "/logout", token)
    assert salida.status_code == 204
    assert "max-age=0" in salida.headers["set-cookie"].lower()

    despues = await _post(cliente, "/refresh", token)
    assert despues.status_code == 401


async def test_logout_sin_sesion_es_idempotente(cliente, datos):
    resp = await _post(cliente, "/logout")
    assert resp.status_code == 204


async def test_origen_no_permitido(cliente, sesiones, datos, monkeypatch):
    monkeypatch.setattr(settings, "allowed_origin", "https://app.test")
    token = await _sesion(sesiones, datos.ana.id)

    malo = await _post(cliente, "/refresh", token, {"Origin": "https://malo.test"})
    assert malo.status_code == 403

    bueno = await _post(cliente, "/refresh", token, {"Origin": "https://app.test"})
    assert bueno.status_code == 200