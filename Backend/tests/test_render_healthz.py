"""Prueba de integración: endpoints de salud del backend (OPS-03).

Verifica que los endpoints /healthz y /readyz responden correctamente usando
el cliente HTTP del conftest (async_client) y dependency_overrides de FastAPI.

Cobertura:
  - GET /healthz → 200 {"status": "ok", "service": "backend"}
  - GET /readyz  → 200 cuando la BD responde SELECT 1 correctamente
  - GET /readyz  → 503 application/problem+json cuando la BD lanza excepción

Nota sobre /healthz vs /readyz:
  - /healthz es el healthCheckPath de Render: lo llama para saber si el
    contenedor está vivo. No depende de la BD.
  - /readyz lo verifica el pipeline deploy-dev (humo post-deploy) para
    confirmar que la BD está conectada antes de dar el deploy por bueno.
    Render no lo llama automáticamente.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.database import obtener_base_datos


# ---------------------------------------------------------------------------
# /healthz — integración real (no depende de BD)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_healthz_devuelve_ok():
    """GET /healthz responde 200 con status 'ok' sin necesitar la BD.

    Render llama a este endpoint continuamente para saber si el proceso
    sigue vivo. No debe depender de ningún recurso externo.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "backend"


@pytest.mark.anyio
async def test_healthz_respuesta_es_json_valido():
    """GET /healthz devuelve un JSON serializable (Content-Type: application/json)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# /readyz — camino feliz: BD responde SELECT 1
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_readyz_devuelve_ready_cuando_bd_responde():
    """GET /readyz responde 200 {"status":"ready"} cuando la BD funciona.

    Sobreescribimos obtener_base_datos con un mock que simula que SELECT 1
    se ejecuta sin error, lo que activa el bloque try de verificar_listo.
    """
    # Sesión falsa: execute() no lanza excepción → camino feliz
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=None)

    async def db_override():
        yield db_mock

    app.dependency_overrides[obtener_base_datos] = db_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/readyz")
    finally:
        app.dependency_overrides.pop(obtener_base_datos, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "connected"


# ---------------------------------------------------------------------------
# /readyz — camino de error: BD no disponible → 503 problem+json
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_readyz_devuelve_503_cuando_bd_falla():
    """GET /readyz responde 503 application/problem+json cuando la BD falla.

    Sobreescribimos obtener_base_datos con un mock que lanza una excepción
    genérica, activando el bloque except de verificar_listo.
    El cuerpo debe seguir el formato RFC 9457 (application/problem+json).
    """
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(side_effect=Exception("Connection refused"))

    async def db_override():
        yield db_mock

    app.dependency_overrides[obtener_base_datos] = db_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/readyz")
    finally:
        app.dependency_overrides.pop(obtener_base_datos, None)

    assert response.status_code == 503
    assert "application/problem+json" in response.headers["content-type"]

    body = response.json()
    assert body["status"] == 503
    assert body["code"] == "DATABASE_UNAVAILABLE"
    assert body["type"] == "about:blank"
    assert "title" in body
    assert "detail" in body
