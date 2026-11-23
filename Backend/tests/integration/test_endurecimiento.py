"""Pruebas de integración del endurecimiento de la API (BE-21).

Cubre el ``TrustedHostMiddleware``, el límite de tamaño del cuerpo y las
cabeceras de seguridad.
"""

import asyncio
import json

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
    """Crea una app mínima con los middlewares de endurecimiento y /healthz."""
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/echo")
    def echo(body: dict) -> dict:
        return body

    if allowed_hosts:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[h.strip().lower() for h in allowed_hosts.split(",") if h.strip()],
        )

    app.add_middleware(
        LimiteCuerpoMiddleware,
        max_body_bytes=max_body_bytes,
    )
    app.add_middleware(CabecerasSeguridadMiddleware)

    return app


def _ejecutar_peticion_chunked(
    app: FastAPI,
    fragmentos: list[bytes],
) -> tuple[int, dict[str, str], bytes]:
    """Ejecuta una petición ASGI cuyo cuerpo llega en varios fragmentos."""

    async def _ejecutar():
        mensajes = iter(
            [
                {
                    "type": "http.request",
                    "body": fragmento,
                    "more_body": i < len(fragmentos) - 1,
                }
                for i, fragmento in enumerate(fragmentos)
            ]
        )
        eventos = []

        async def receive():
            try:
                return next(mensajes)
            except StopIteration:
                return {"type": "http.disconnect"}

        async def send(mensaje):
            eventos.append(mensaje)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/echo",
            "raw_path": b"/echo",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"transfer-encoding", b"chunked"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }

        await app(scope, receive, send)

        inicio = next(evento for evento in eventos if evento["type"] == "http.response.start")
        cuerpo = b"".join(
            evento.get("body", b"") for evento in eventos if evento["type"] == "http.response.body"
        )
        cabeceras = {
            nombre.decode("latin-1").lower(): valor.decode("latin-1")
            for nombre, valor in inicio.get("headers", [])
        }

        return inicio["status"], cabeceras, cuerpo

    return asyncio.run(_ejecutar())


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
        return TestClient(
            _crear_app(
                allowed_hosts=allowed_hosts,
                max_body_bytes=max_body_bytes,
            )
        )

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
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.status_code == 400


def test_cuerpo_demasiado_grande(crear_cliente) -> None:
    """Un cuerpo mayor a ``MAX_BODY_BYTES`` responde 413 con RFC 9457."""
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
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_cuerpo_dentro_del_limite(crear_cliente) -> None:
    """Un cuerpo menor al límite no lo rechaza el middleware."""
    cliente = crear_cliente(max_body_bytes=1024)
    r = cliente.post("/echo", json={"ok": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_cuerpo_chunked_dentro_del_limite() -> None:
    """Acepta un cuerpo chunked dentro del límite y conserva su contenido."""
    app = _crear_app(max_body_bytes=1024)
    payload = json.dumps({"mensaje": "prueba chunked"}).encode("utf-8")
    fragmentos = [payload[:10], payload[10:]]

    status, headers, cuerpo = _ejecutar_peticion_chunked(app, fragmentos)

    assert status == 200
    assert json.loads(cuerpo) == {"mensaje": "prueba chunked"}
    assert headers["content-type"].startswith("application/json")


def test_cuerpo_chunked_supera_el_limite() -> None:
    """Rechaza con 413 un cuerpo chunked que supera el límite."""
    app = _crear_app(max_body_bytes=20)
    payload = json.dumps({"mensaje": "este cuerpo supera el límite"}).encode("utf-8")
    fragmentos = [payload[:10], payload[10:20], payload[20:]]

    status, headers, cuerpo = _ejecutar_peticion_chunked(app, fragmentos)

    assert status == 413
    assert headers["content-type"].startswith("application/problem+json")
    assert json.loads(cuerpo)["code"] == "PAYLOAD_TOO_LARGE"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_cabeceras_de_seguridad(crear_cliente) -> None:
    """Toda respuesta incluye las cabeceras de seguridad y NO la obsoleta."""
    cliente = crear_cliente()
    r = cliente.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "max-age=31536000" in r.headers["strict-transport-security"]
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "x-xss-protection" not in r.headers


def test_app_real_healthz_tiene_cabeceras() -> None:
    """Prueba sobre la app real (Punto 4 del review)."""
    from app.main import app

    cliente = TestClient(app)
    r = cliente.get("/healthz")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
