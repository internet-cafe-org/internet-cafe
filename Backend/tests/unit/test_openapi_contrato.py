"""Coherencia estática de openapi.yaml v0.2.1. No necesita base de datos ni la app."""

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
DOC = yaml.safe_load((RAIZ / "openapi.yaml").read_text(encoding="utf-8"))
MD = (RAIZ / "contrato.md").read_text(encoding="utf-8")

NUEVAS = [
    ("/api/v1/machine/heartbeat", "post"),
    ("/api/v1/machine/sessions/current", "get"),
    ("/api/v1/machine/sessions/current/end", "post"),
    ("/api/v1/me", "get"),
    ("/api/v1/me/sessions", "get"),
    ("/api/v1/me/sessions/active", "get"),
    ("/api/v1/me/sessions/{id}/end", "post"),
    ("/api/v1/admin/labs", "get"),
    ("/api/v1/admin/labs", "post"),
    ("/api/v1/admin/machines", "get"),
    ("/api/v1/admin/machines/{id}", "patch"),
    ("/api/v1/admin/sessions", "get"),
    ("/api/v1/admin/sessions/{id}/end", "post"),
    ("/api/v1/admin/machines/{id}/enrollment-code", "post"),
    ("/api/v1/admin/machines/{id}/revoke-key", "post"),
]

NUEVAS_V021 = [
    ("/healthz", "get"),
    ("/readyz", "get"),
    ("/api/v1/auth/register", "post"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/refresh", "post"),
    ("/api/v1/auth/logout", "post"),
    ("/api/v1/machine/enroll", "post"),
]

FANTASMAS_V01 = [
    "/api/v1/registro",
    "/api/v1/enroll",
    "/api/v1/credencial-provisional",
    "/api/v1/long-poll",
]


def _refs(nodo):
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if k == "$ref":
                yield v
            else:
                yield from _refs(v)
    elif isinstance(nodo, list):
        for i in nodo:
            yield from _refs(i)


def _seguridad(ruta: str, metodo: str) -> list[str]:
    """Devuelve los nombres de los esquemas de seguridad de una operación.

    Args:
        ruta: Ruta tal como aparece en `paths`.
        metodo: Método HTTP en minúsculas.

    Returns:
        Lista con el nombre de cada esquema exigido.
    """
    return [nombre for req in DOC["paths"][ruta][metodo].get("security", []) for nombre in req]


def test_version_0_2_1() -> None:
    assert DOC["info"]["version"] == "0.2.1"


@pytest.mark.parametrize(("ruta", "metodo"), NUEVAS)
def test_endpoints_v02_documentados(ruta: str, metodo: str) -> None:
    assert metodo in DOC["paths"][ruta]


@pytest.mark.parametrize(("ruta", "metodo"), NUEVAS_V021)
def test_endpoints_v021_documentados(ruta: str, metodo: str) -> None:
    assert metodo in DOC["paths"][ruta]


@pytest.mark.parametrize("ruta", FANTASMAS_V01)
def test_sin_rutas_fantasma_de_v01(ruta: str) -> None:
    assert ruta not in DOC["paths"]


@pytest.mark.parametrize("ruta", ["/api/v1/scan/preview", "/api/v1/scan/claim"])
def test_scan_exige_access_token(ruta: str) -> None:
    assert _seguridad(ruta, "post") == ["bearerAuth"]
    assert "401" in DOC["paths"][ruta]["post"]["responses"]


@pytest.mark.parametrize(
    ("ruta", "metodo"),
    [("/api/v1/machine/challenges", "post"), ("/api/v1/machine/challenges/wait", "get")],
)
def test_retos_usan_la_autenticacion_del_equipo(ruta: str, metodo: str) -> None:
    assert _seguridad(ruta, metodo) == ["machineSignature", "machineProvisional"]
    cabeceras = {p["name"].lower() for p in DOC["paths"][ruta][metodo].get("parameters", [])}
    assert "x-machine-code" not in cabeceras


def test_registro_responde_siempre_202() -> None:
    respuestas = DOC["paths"]["/api/v1/auth/register"]["post"]["responses"]
    assert "202" in respuestas
    assert not {"200", "201", "409"} & set(respuestas)


def test_cookie_de_refresh_se_llama_secure_rt() -> None:
    for ruta in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
        nombres = {p["name"] for p in DOC["paths"][ruta]["post"]["parameters"] if p["in"] == "cookie"}
        assert nombres == {"__Secure-rt"}
    cabecera = DOC["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]["headers"]["Set-Cookie"]
    assert "__Secure-rt" in cabecera["description"]


def test_todas_las_referencias_resuelven() -> None:
    comp = DOC["components"]
    for r in _refs(DOC):
        m = re.fullmatch(r"#/components/(schemas|responses)/(\w+)", r)
        assert m and m.group(2) in comp[m.group(1)], r


def test_errores_usan_problem_json() -> None:
    for resp in DOC["components"]["responses"].values():
        assert "application/problem+json" in resp["content"]


def test_los_esquemas_no_exponen_secretos() -> None:
    prohibidos = {"password", "password_hash", "token", "key_thumbprint", "machine_key", "student_code"}
    for nombre, esquema in DOC["components"]["schemas"].items():
        assert not prohibidos & set(esquema.get("properties", {})), nombre


def test_contrato_md_incluye_el_mismo_yaml() -> None:
    bloque = MD.split("```yaml\n", 1)[1].rsplit("```", 1)[0]
    assert yaml.safe_load(bloque) == DOC
