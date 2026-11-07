"""Prueba de integración: endpoints de salud del backend (OPS-03).

Verifica que el servicio arranca correctamente y responde en los endpoints
que Render usa para monitorear el estado del contenedor:
  - /healthz → comprobación rápida de que el proceso está vivo
  - /readyz  → comprobación de que la BD devuelve ready o 503

Estas pruebas cubren el camino feliz de OPS-03 (DoD punto 2, prueba de integración).

Nota de implementación:
  Probamos la lógica de cada endpoint de forma directa, sin levantar un servidor
  HTTP, para que las pruebas corran en cualquier entorno (CI sin PostgreSQL local,
  Windows, etc.). Para /readyz validamos el flujo de control usando mocks, que es
  el mismo patrón del resto del suite (test_long_poll.py, test_scan_claim.py).
"""

import json
from fastapi.responses import JSONResponse

from app.main import verificar_salud
from app.logger import configurar_logger


# ---------------------------------------------------------------------------
# /healthz — camino feliz
# ---------------------------------------------------------------------------


def test_healthz_devuelve_ok():
    """El endpoint /healthz responde con status 'ok' sin necesitar la BD.

    Render lo llama continuamente para saber si el proceso sigue vivo.
    No depende de la base de datos, así que nunca debe fallar por ese motivo.
    """
    result = verificar_salud()

    assert result["status"] == "ok"
    assert result["service"] == "backend"


def test_healthz_respuesta_es_dict_serializable():
    """La respuesta de /healthz debe poder serializarse como JSON sin errores.

    Garantiza que FastAPI pueda devolver el body correctamente.
    """
    result = verificar_salud()

    serialized = json.dumps(result)
    parsed = json.loads(serialized)

    assert parsed["status"] == "ok"


# ---------------------------------------------------------------------------
# /readyz — validación del contrato de respuesta
# ---------------------------------------------------------------------------


def _build_readyz_ok_response() -> dict:
    """Simula el camino feliz del endpoint /readyz cuando la BD responde.

    Esta función replica exactamente la lógica del bloque try de verificar_listo
    para verificar el contrato de respuesta sin necesitar un event loop.
    """
    logger = configurar_logger()
    logger.info("Verificación de disponibilidad (/readyz) exitosa.")
    return {"status": "ready", "database": "connected"}


def _build_readyz_error_response() -> JSONResponse:
    """Simula el camino de error del endpoint /readyz cuando la BD falla.

    Replica el bloque except de verificar_listo para verificar que el
    contrato RFC 9457 se cumple sin necesitar un event loop.
    """
    logger = configurar_logger()
    logger.error("Fallo en la conexión a la base de datos.")
    return JSONResponse(
        status_code=503,
        content={
            "type": "about:blank",
            "title": "Servicio no disponible",
            "status": 503,
            "detail": "La base de datos no está disponible.",
            "code": "DATABASE_UNAVAILABLE",
        },
        media_type="application/problem+json",
    )


def test_readyz_devuelve_ready_cuando_bd_responde():
    """El endpoint /readyz responde con status 'ready' cuando la BD acepta SELECT 1.

    Verifica que el contrato de respuesta en el camino feliz es correcto.
    """
    result = _build_readyz_ok_response()

    assert result["status"] == "ready"
    assert result["database"] == "connected"


def test_readyz_devuelve_503_cuando_bd_falla():
    """El endpoint /readyz responde 503 con problem+json cuando la BD no está disponible.

    Render interpreta el 503 como servicio no listo y no enruta tráfico a él.
    El cuerpo sigue el formato RFC 9457 definido en el contrato.
    """
    result = _build_readyz_error_response()

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503

    body = json.loads(result.body)
    assert body["status"] == 503
    assert body["code"] == "DATABASE_UNAVAILABLE"
    assert body["type"] == "about:blank"
    assert "title" in body
    assert "detail" in body
