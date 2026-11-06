"""Cuerpo de creación de proyectos de Neon con tope de 0,25 CU (OPS-02)."""

import json

import pytest

from tools.neon_projects import TOPE_CU, construir_payload, main


@pytest.mark.parametrize("entorno", ["dev", "prod"])
def test_payload_fija_el_tope_de_cu_en_0_25(entorno: str) -> None:
    proyecto = construir_payload(entorno)["project"]
    ajustes = proyecto["default_endpoint_settings"]
    assert TOPE_CU == 0.25
    assert ajustes["autoscaling_limit_min_cu"] == 0.25
    assert ajustes["autoscaling_limit_max_cu"] == 0.25
    assert proyecto["name"] == f"internet-cafe-{entorno}"
    assert proyecto["pg_version"] == 17


def test_dev_y_prod_son_proyectos_distintos() -> None:
    assert construir_payload("dev")["project"]["name"] != construir_payload("prod")["project"]["name"]


def test_entorno_desconocido_se_rechaza() -> None:
    with pytest.raises(ValueError):
        construir_payload("staging")


def test_dry_run_no_usa_la_red_ni_pide_clave(capsys, monkeypatch) -> None:
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    assert main(["--env", "dev"]) == 0
    salida = capsys.readouterr().out
    assert "DRY-RUN" in salida
    assert json.loads(salida.split("\n", 1)[1])["project"]["name"] == "internet-cafe-dev"


def test_apply_sin_clave_falla_sin_llamar_a_neon(monkeypatch) -> None:
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    assert main(["--env", "prod", "--apply"]) == 2
