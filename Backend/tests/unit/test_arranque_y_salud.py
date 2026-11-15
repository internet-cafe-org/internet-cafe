"""Arranque sin llaves (HU-07, BE-02), ``/readyz`` con 503 y logger JSON.

No necesitan base de datos: ``/readyz`` se prueba con una sesión falsa que falla.
"""

import json
import logging

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.config import settings
from app.database import obtener_base_datos
from app.logger import JSONFormatter
from app.main import app
from app.security.arranque import LlavesInvalidas, verificar_llaves


def _par() -> tuple[str, str]:
    """Genera un par ES256 en PEM.

    Returns:
        La llave privada y la pública.
    """
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    publica = clave.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return privada, publica


@pytest.fixture
def llaves_validas(monkeypatch) -> None:
    """Configura un par ES256 válido y la llave del índice ciego."""
    privada, publica = _par()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    monkeypatch.setattr(settings, "blind_index_key", bytes(range(32)).hex())


def test_llaves_validas_pasan(llaves_validas) -> None:
    """Con el par y la llave del índice la verificación no falla."""
    verificar_llaves()


@pytest.mark.parametrize("variable", ["jwt_private_key", "jwt_public_key", "blind_index_key"])
def test_falta_una_llave(llaves_validas, monkeypatch, variable) -> None:
    """Si falta una llave, el error nombra la variable."""
    monkeypatch.setattr(settings, variable, None)

    with pytest.raises(LlavesInvalidas, match=variable.upper()):
        verificar_llaves()


def test_llaves_que_no_forman_un_par(llaves_validas, monkeypatch) -> None:
    """Una pública de otro par se detecta, y el mensaje no incluye la llave."""
    _, otra_publica = _par()
    monkeypatch.setattr(settings, "jwt_public_key", otra_publica)

    with pytest.raises(LlavesInvalidas) as error:
        verificar_llaves()
    assert "BEGIN" not in str(error.value)


def test_la_api_no_arranca_sin_llaves(monkeypatch) -> None:
    """El ``lifespan`` corta el arranque si faltan las llaves."""
    monkeypatch.setattr(settings, "jwt_private_key", None)

    with pytest.raises(LlavesInvalidas), TestClient(app):
        pass


def test_la_api_arranca_con_llaves(llaves_validas) -> None:
    """Con llaves válidas el ``lifespan`` deja pasar y ``/healthz`` responde."""
    with TestClient(app) as cliente:
        r = cliente.get("/healthz")

    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "backend"}


def test_readyz_sin_base_responde_503_del_catalogo() -> None:
    """Si la base falla, ``/readyz`` responde 503 con un ``code`` del catálogo."""

    class BaseCaida:
        async def execute(self, *_args, **_kwargs):
            raise ConnectionError("sin conexión")

    app.dependency_overrides[obtener_base_datos] = lambda: BaseCaida()
    try:
        r = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.pop(obtener_base_datos, None)

    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    cuerpo = r.json()
    assert cuerpo["code"] == "INTERNAL_ERROR"
    assert cuerpo["status"] == 503
    assert "sin conexión" not in r.text


def test_el_logger_json_incluye_los_datos_del_evento() -> None:
    """Los datos de ``extra={"datos": ...}`` salen como campos del JSON."""
    registro = logging.LogRecord("internet_cafe_backend.auth", logging.INFO, __file__, 1,
                                 "auth.login", None, None)
    registro.datos = {"evento": "auth.login", "resultado": "ok", "level": "no-pisa"}

    salida = json.loads(JSONFormatter().format(registro))

    assert salida["evento"] == "auth.login"
    assert salida["resultado"] == "ok"
    assert salida["level"] == "INFO"
