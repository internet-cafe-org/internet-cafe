"""Coherencia estática de openapi.yaml v0.2 (BE-18). No necesita base de datos ni la app."""

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
DOC = yaml.safe_load((RAIZ / "openapi.yaml").read_text(encoding="utf-8"))
MD = (RAIZ / "Contrato.md").read_text(encoding="utf-8")

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


def test_version_0_2_0() -> None:
    assert DOC["info"]["version"] == "0.2.0"


@pytest.mark.parametrize(("ruta", "metodo"), NUEVAS)
def test_endpoints_v02_documentados(ruta: str, metodo: str) -> None:
    assert metodo in DOC["paths"][ruta]


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
