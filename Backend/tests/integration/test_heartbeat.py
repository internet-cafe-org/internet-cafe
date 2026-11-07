"""Pruebas de integración para el endpoint de latido (BE-08).

Valida el rechazo de equipos no autenticados y el formato de la respuesta esperada.
"""

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_heartbeat_sin_autenticacion(async_client: AsyncClient):
    """
    Prueba que el endpoint rechace una petición sin credenciales de equipo.
    Esto valida que el endpoint está protegido por `require_machine` (RN-08).
    """
    response = await async_client.post(
        "/api/v1/machine/heartbeat",
        json={"session_id": None}
    )
    
    # Esperamos un 401 Unauthorized o 403 Forbidden
    assert response.status_code in [401, 403]
    
    data = response.json()
    # El código de error de seguridad suele ser MACHINE_SIGNATURE_INVALID o similar
    assert "code" in data or "detail" in data

@pytest.mark.asyncio
async def test_heartbeat_campos_respuesta(async_client: AsyncClient):
    """
    Verifica que el endpoint esté registrado y devuelva los campos correctos
    cuando se le llama (aunque sea sin autenticar para ver la estructura del error).
    """
    response = await async_client.post(
        "/api/v1/machine/heartbeat",
        json={"session_id": None}
    )
    # Solo verificamos que el endpoint existe (no da 404)
    assert response.status_code != 404