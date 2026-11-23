"""SEC-02: pruebas de PATCH /me/password contra la API real y PostgreSQL.

Cubre el camino feliz (hash nuevo, 204, auditoría sin contraseñas), la contraseña
actual incorrecta, la política de largo, las sesiones web y los casos sin token.
Las fixtures `claves` y `cliente` repiten las de test_me_estudiante.py para no
modificar ese archivo.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import AuditLog, RefreshToken, User
from app.routers.auth import COOKIE_NAME
from app.services import refresh_tokens
from app.services.passwords import hash_password, verify_password

API = "/api/v1"
CLAVE_ACTUAL = "ClaveActual-2026"
CLAVE_NUEVA = "ClaveNueva-2026-ok"


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> str:
    """Claves ES256 efímeras para la API; devuelve la privada con la que firma."""
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
    return privada


@pytest.fixture
async def cliente(
    sesiones: async_sessionmaker[AsyncSession], claves: str
) -> AsyncIterator[AsyncClient]:
    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _bearer(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(subject=str(usuario.id), role="student", private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _con_clave(sesiones: async_sessionmaker[AsyncSession], usuario: User) -> None:
    """Le pone al estudiante una contraseña real (la fixture trae un hash falso)."""
    async with sesiones() as db:
        fila = await db.get(User, usuario.id)
        assert fila is not None
        fila.password_hash = hash_password(CLAVE_ACTUAL)
        await db.commit()


async def _hash_guardado(sesiones: async_sessionmaker[AsyncSession], usuario: User) -> str:
    async with sesiones() as db:
        return (
            await db.execute(select(User.password_hash).where(User.id == usuario.id))
        ).scalar_one()


async def _revocado_en(sesiones: async_sessionmaker[AsyncSession], token: str) -> Any:
    async with sesiones() as db:
        return (
            await db.execute(
                select(RefreshToken.revoked_at).where(
                    RefreshToken.token_hash == refresh_tokens.hash_token(token)
                )
            )
        ).scalar_one()


async def test_cambia_la_contrasena_y_deja_auditoria(
    cliente: AsyncClient,
    claves: str,
    datos: Any,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": CLAVE_NUEVA},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 204
    assert resp.content == b""
    guardado = await _hash_guardado(sesiones, datos.ana)
    assert verify_password(CLAVE_NUEVA, guardado)
    assert not verify_password(CLAVE_ACTUAL, guardado)
    async with sesiones() as db:
        filas = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "auth.password_change")))
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert filas[0].actor_id == datos.ana.id
    texto = str(filas[0].metadata_info)
    assert CLAVE_NUEVA not in texto
    assert CLAVE_ACTUAL not in texto


async def test_contrasena_actual_incorrecta_no_cambia_nada(
    cliente: AsyncClient,
    claves: str,
    datos: Any,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": "OtraClave-incorrecta", "new_password": CLAVE_NUEVA},
        headers=_bearer(claves, datos.ana),
    )

    # RF-AUT-10: 401 con un código propio, distinto de los del token (el cliente no
    # debe renovar ni cerrar la sesión por una contraseña mal escrita)
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_CURRENT_PASSWORD_INVALID"
    assert resp.json()["detail"] == "La contraseña actual no es correcta."
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert CLAVE_NUEVA not in resp.text
    assert "OtraClave-incorrecta" not in resp.text
    assert verify_password(CLAVE_ACTUAL, await _hash_guardado(sesiones, datos.ana))


async def test_contrasena_nueva_demasiado_corta(
    cliente: AsyncClient,
    claves: str,
    datos: Any,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": "corta"},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert "corta" not in resp.text
    assert verify_password(CLAVE_ACTUAL, await _hash_guardado(sesiones, datos.ana))


async def test_contrasena_nueva_igual_a_la_actual(
    cliente: AsyncClient,
    claves: str,
    datos: Any,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": CLAVE_ACTUAL},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_rechaza_campos_desconocidos(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": CLAVE_NUEVA, "extra": 1},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 422


async def test_sin_token_responde_401(cliente: AsyncClient, datos: Any) -> None:
    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": CLAVE_NUEVA},
    )

    assert resp.status_code == 401


async def test_cierra_las_otras_sesiones_web_y_conserva_la_actual(
    cliente: AsyncClient,
    claves: str,
    datos: Any,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await _con_clave(sesiones, datos.ana)
    async with sesiones() as db:
        actual = await refresh_tokens.emitir(db, datos.ana.id)
        otra = await refresh_tokens.emitir(db, datos.ana.id)
        await db.commit()

    resp = await cliente.patch(
        f"{API}/me/password",
        json={"current_password": CLAVE_ACTUAL, "new_password": CLAVE_NUEVA},
        headers={**_bearer(claves, datos.ana), "Cookie": f"{COOKIE_NAME}={actual}"},
    )

    assert resp.status_code == 204
    assert await _revocado_en(sesiones, actual) is None
    assert await _revocado_en(sesiones, otra) is not None