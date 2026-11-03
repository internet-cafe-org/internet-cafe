"""Pruebas de integración del formato de errores RFC 9457 (QA-03)."""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.error_handlers import registrar_manejadores
from app.errors import PROBLEM_MEDIA_TYPE, AppError, ErrorCode
from app.main import app as app_real

CONTRASENA = "corta1"


class RegistroPrueba(BaseModel):
    """Imita el body de /auth/register hasta que exista el endpoint real."""

    model_config = ConfigDict(extra="forbid")

    correo: str
    password: str = Field(min_length=12)


def _crear_app_prueba() -> FastAPI:
    app = FastAPI()
    registrar_manejadores(app)

    @app.post("/auth/register", status_code=201)
    def registrar(body: RegistroPrueba) -> dict[str, str]:
        return {"correo": body.correo}

    @app.get("/reto-vencido")
    def reto_vencido() -> None:
        raise AppError(ErrorCode.CHALLENGE_EXPIRED)

    @app.get("/limitado")
    def limitado() -> None:
        raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"})

    @app.get("/http-con-code")
    def http_con_code() -> None:
        raise HTTPException(409, detail={"code": "MACHINE_BUSY"})

    @app.get("/http-sin-catalogo")
    def http_sin_catalogo() -> None:
        raise HTTPException(418, detail="texto que no debe salir")

    @app.get("/explota")
    def explota() -> None:
        raise RuntimeError(f"fallo interno con {CONTRASENA}")

    return app


@pytest.fixture
def cliente() -> TestClient:
    # Sin relanzar: así se ve la respuesta 500 que recibe el cliente real
    return TestClient(_crear_app_prueba(), raise_server_exceptions=False)


def _es_problema(respuesta) -> dict:
    assert respuesta.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    return respuesta.json()


def test_422_contrasena_corta_formato_problem(cliente: TestClient) -> None:
    r = cliente.post(
        "/auth/register", json={"correo": "a@b.co", "password": CONTRASENA}
    )

    assert r.status_code == 422
    cuerpo = _es_problema(r)
    assert cuerpo["code"] == "VALIDATION_ERROR"
    assert cuerpo["status"] == 422
    assert cuerpo["instance"] == "/auth/register"
    assert cuerpo["errors"][0]["field"] == "body.password"
    assert cuerpo["errors"][0]["message"]


def test_422_no_devuelve_input_ni_valor_enviado(cliente: TestClient) -> None:
    r = cliente.post(
        "/auth/register", json={"correo": "a@b.co", "password": CONTRASENA}
    )

    cuerpo = _es_problema(r)
    for error in cuerpo["errors"]:
        assert set(error) == {"field", "message"}
    assert CONTRASENA not in r.text
    assert "input" not in json.dumps(cuerpo)


def test_422_campo_desconocido(cliente: TestClient) -> None:
    r = cliente.post(
        "/auth/register",
        json={"correo": "a@b.co", "password": "x" * 12, "es_admin": "secreto"},
    )

    assert r.status_code == 422
    cuerpo = _es_problema(r)
    assert cuerpo["code"] == "VALIDATION_ERROR"
    assert cuerpo["errors"][0]["field"] == "body.es_admin"
    assert "secreto" not in r.text


def test_422_json_mal_formado(cliente: TestClient) -> None:
    r = cliente.post(
        "/auth/register",
        content=f'{{"password": "{CONTRASENA}"',
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 422
    assert _es_problema(r)["code"] == "VALIDATION_ERROR"
    assert CONTRASENA not in r.text


def test_app_error_challenge_expired(cliente: TestClient) -> None:
    r = cliente.get("/reto-vencido?token=no-debe-salir")

    assert r.status_code == 410
    assert _es_problema(r) == {
        "type": ErrorCode.CHALLENGE_EXPIRED.type_uri,
        "title": "El código QR expiró",
        "status": 410,
        "code": "CHALLENGE_EXPIRED",
        "detail": "Escanea el código nuevo del equipo.",
        "instance": "/reto-vencido",
    }
    assert r.json()["type"].endswith("/challenge-expired")


def test_app_error_conserva_headers(cliente: TestClient) -> None:
    r = cliente.get("/limitado")

    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert _es_problema(r)["code"] == "RATE_LIMITED"


def test_http_exception_con_code_usa_catalogo(cliente: TestClient) -> None:
    r = cliente.get("/http-con-code")

    assert r.status_code == 409
    assert _es_problema(r)["code"] == "MACHINE_BUSY"


def test_http_exception_sin_catalogo_no_filtra_detail(cliente: TestClient) -> None:
    r = cliente.get("/http-sin-catalogo")

    assert r.status_code == 418
    cuerpo = _es_problema(r)
    assert cuerpo["code"] == "BAD_REQUEST"
    assert "texto que no debe salir" not in r.text


def test_500_sin_traza(cliente: TestClient) -> None:
    r = cliente.get("/explota")

    assert r.status_code == 500
    cuerpo = _es_problema(r)
    assert cuerpo["code"] == "INTERNAL_ERROR"
    assert "RuntimeError" not in r.text
    assert "Traceback" not in r.text
    assert CONTRASENA not in r.text
    assert r.headers["x-request-id"]


def test_app_real_ruta_inexistente_404() -> None:
    r = TestClient(app_real).get("/api/v1/no-existe")

    assert r.status_code == 404
    cuerpo = _es_problema(r)
    assert cuerpo["code"] == "NOT_FOUND"
    assert cuerpo["instance"] == "/api/v1/no-existe"


def test_app_real_metodo_no_permitido_405() -> None:
    r = TestClient(app_real).delete("/healthz")

    assert r.status_code == 405
    assert _es_problema(r)["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in r.headers["allow"]


def test_app_real_422_sin_body() -> None:
    r = TestClient(app_real).post("/api/v1/scan/preview", json={})

    assert r.status_code == 422
    cuerpo = _es_problema(r)
    assert cuerpo["errors"] == [{"field": "body.token", "message": "Field required"}]


def test_openapi_422_usa_problem_detail() -> None:
    esquema = TestClient(app_real).get("/openapi.json").json()

    schemas = esquema["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ProblemDetail" in schemas
    respuesta_422 = esquema["paths"]["/api/v1/scan/preview"]["post"]["responses"]["422"]
    assert respuesta_422["content"] == {
        PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
    }
    assert "HTTPValidationError" not in json.dumps(esquema)
