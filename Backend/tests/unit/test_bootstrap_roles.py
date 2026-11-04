"""Revisión estática de db/bootstrap_roles.sql (OPS-02).

La prueba con PostgreSQL real (roles, privilegios, DELETE denegado) está en
tests/integration/test_roles_bootstrap.py; esta es rápida y corre siempre.
"""

import re
from pathlib import Path

import pytest

SQL = (Path(__file__).resolve().parents[2] / "db" / "bootstrap_roles.sql").read_text(encoding="utf-8")


def _sin_comentarios(sql: str) -> str:
    return "\n".join(linea.split("--", 1)[0] for linea in sql.splitlines())


CODIGO = _sin_comentarios(SQL)


def test_define_los_dos_roles_de_servicio() -> None:
    assert "svc_migrator" in CODIGO
    assert "svc_app" in CODIGO


def test_las_contrasenas_llegan_por_variables_de_psql_y_no_estan_en_el_archivo() -> None:
    assert ":'migrator_password'" in CODIGO
    assert ":'app_password'" in CODIGO
    # Ningún PASSWORD con literal entre comillas escrito a mano
    assert not re.search(r"PASSWORD\s+'[^']", CODIGO, re.IGNORECASE)


def test_los_roles_se_crean_con_el_minimo_privilegio() -> None:
    for atributo in ("NOINHERIT", "NOCREATEDB", "NOCREATEROLE", "NOSUPERUSER", "NOBYPASSRLS"):
        assert atributo in CODIGO


def test_privilegios_por_defecto_solo_select_insert_update() -> None:
    por_defecto = re.findall(
        r"ALTER DEFAULT PRIVILEGES.*?GRANT\s+(.*?)\s+ON\s+TABLES\s+TO\s+svc_app",
        CODIGO,
        re.IGNORECASE | re.DOTALL,
    )
    assert [p.upper() for p in por_defecto] == ["SELECT, INSERT, UPDATE"]


@pytest.mark.parametrize("privilegio", ["DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "ALL PRIVILEGES"])
def test_ningun_grant_concede_privilegios_peligrosos_a_svc_app(privilegio: str) -> None:
    for grant in re.findall(r"GRANT\s+[^;]*?\s+TO\s+[^;]*svc_app[^;]*;", CODIGO, re.IGNORECASE | re.DOTALL):
        assert privilegio not in grant.upper(), grant


def test_la_app_no_recibe_create_en_ningun_esquema() -> None:
    for grant in re.findall(r"GRANT\s+[^;]*?\s+TO\s+svc_app\s*;", CODIGO, re.IGNORECASE | re.DOTALL):
        assert "CREATE" not in grant.upper(), grant


def test_exige_contrasenas_de_32_o_mas_caracteres() -> None:
    assert ">= 32" in CODIGO


def test_public_queda_sin_privilegios() -> None:
    assert "REVOKE ALL ON SCHEMA public FROM PUBLIC" in CODIGO


def test_timeouts_de_la_app_segun_el_srs() -> None:
    assert "ALTER ROLE svc_app SET statement_timeout = '5s'" in CODIGO
    assert "ALTER ROLE svc_app SET idle_in_transaction_session_timeout = '10s'" in CODIGO
