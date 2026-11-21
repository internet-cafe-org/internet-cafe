"""Pruebas de integración del endurecimiento de la API (BE-21).

Cubre el ``TrustedHostMiddleware``, el límite de tamaño del cuerpo y las
cabeceras de seguridad. Para no depender de BD ni de llaves criptográficas,
cada prueba construye una app mínima con los middlewares de ``app.main``.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.main import CabecerasSeguridadMiddleware, LimiteCuerpoMiddleware


def _crear_app(
    *,
    allowed_hosts: str = "",
    max_body_bytes: int = 65536,
) -> FastAPI:
    """Crea una app mínima con los middlewares de endurecimiento y /healthz.

    Replica el orden de registro de ``app.main``: el último agregado
    (``TrustedHostMiddleware``) es el primero en ejecutarse.
    """
    app = FastAPI()

    # Endpoint simple para probar los middlewares sin tocar BD ni llaves.
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/echo")
    def echo(body: dict) -> dict:
        return body

    app.add_middleware(CabecerasSeguridadMiddleware)
    app.add_middleware(LimiteCuerpoMiddleware)
    if allowed_hosts:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[h.strip().lower() for h in allowed_hosts.split(",") if h.strip()],
        )
    return app


@pytest.fixture
def crear_cliente(monkeypatch):
    """Devuelve una fábrica que crea un ``TestClient`` con la config indicada."""

    def _crear(
        *,
        allowed_hosts: str = "",
        max_body_bytes: int = 65536,
    ) -> TestClient:
        monkeypatch.setattr(settings, "allowed_hosts", allowed_hosts)
        monkeypatch.setattr(settings, "max_body_bytes", max_body_bytes)
        return TestClient(_crear_app(allowed_hosts=allowed_hosts, max_body_bytes=max_body_bytes))

    return _crear


def test_host_permitido(crear_cliente) -> None:
    """Un host de ``ALLOWED_HOSTS`` responde 200 en /healthz."""
    cliente = crear_cliente(allowed_hosts="testserver,localhost")
    r = cliente.get("/healthz")
    assert r.status_code == 200


def test_host_no_permitido(crear_cliente) -> None:
    """Un host fuera de la lista responde 400."""
    cliente = crear_cliente(allowed_hosts="otro-host.com")
    r = cliente.get("/healthz", headers={"Host": "malicioso.com"})
    assert r.status_code == 400


def test_host_vacio_no_restringe(crear_cliente) -> None:
    """Si ``ALLOWED_HOSTS`` está vacío, no se restringe el host."""
    cliente = crear_cliente(allowed_hosts="")
    r = cliente.get("/healthz", headers={"Host": "cualquier-cosa.com"})
    assert r.status_code == 200


def test_cuerpo_demasiado_grande(crear_cliente) -> None:
    """Un cuerpo mayor a ``MAX_BODY_BYTES`` responde 413."""
    cliente = crear_cliente(max_body_bytes=1024)
    payload = "a" * 2048
    r = cliente.post(
        "/echo",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        },
    )
    assert r.status_code == 413
    assert r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_cuerpo_dentro_del_limite(crear_cliente) -> None:
    """Un cuerpo menor al límite no lo rechaza el middleware."""
    cliente = crear_cliente(max_body_bytes=1024)
    r = cliente.post("/echo", json={"ok": True})
    # El middleware no lo rechaza; la app responde 200 con el eco.
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_cabeceras_de_seguridad(crear_cliente) -> None:
    """Toda respuesta incluye las cabeceras de seguridad."""
    cliente = crear_cliente()
    r = cliente.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-xss-protection"] == "1; mode=block"
    assert "max-age=31536000" in r.headers["strict-transport-security"]
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"