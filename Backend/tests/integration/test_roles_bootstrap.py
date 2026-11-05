"""bootstrap_roles.sql contra PostgreSQL real (OPS-02).

Comprueba lo que de verdad importa: que `svc_app` solo pueda SELECT, INSERT y UPDATE,
que las tablas futuras hereden esos privilegios y que el script sea idempotente.

Los roles son GLOBALES del clúster, así que la prueba solo corre si se pide
explícitamente y contra una base desechable:

    TEST_ROLES_ADMIN_URL=postgresql://postgres@localhost:5432/internet_cafe_test_roles \
        python -m pytest tests/integration/test_roles_bootstrap.py

La URL debe ser de un superusuario (lee pg_authid y hace DROP OWNED) y el nombre de la base
debe contener "test". Necesita el cliente `psql` en el PATH. Al terminar elimina los roles.
"""

import os
import secrets
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

SQL = Path(__file__).resolve().parents[2] / "db" / "bootstrap_roles.sql"


@dataclass
class Entorno:
    admin: str
    migrator: str
    app: str
    app_password: str


def _con_credenciales(url: str, usuario: str, contrasena: str) -> str:
    partes = urlsplit(url)
    host = partes.hostname or "localhost"
    puerto = f":{partes.port}" if partes.port else ""
    return urlunsplit((partes.scheme, f"{usuario}:{contrasena}@{host}{puerto}", partes.path, "", ""))


def psql(url: str, *args: str, sql: str | None = None) -> subprocess.CompletedProcess:
    comando = ["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-At", *args]
    if sql is not None:
        comando += ["-c", sql]
    return subprocess.run(comando, capture_output=True, text=True, check=False)


def ejecutar_bootstrap(admin: str, migrator_pw: str, app_pw: str) -> subprocess.CompletedProcess:
    return psql(
        admin,
        "-v", f"migrator_password={migrator_pw}",
        "-v", f"app_password={app_pw}",
        "-f", str(SQL),
    )


@pytest.fixture(scope="module")
def entorno() -> Iterator[Entorno]:
    admin = os.environ.get("TEST_ROLES_ADMIN_URL")
    if not admin:
        pytest.skip("TEST_ROLES_ADMIN_URL no está definida")
    if shutil.which("psql") is None:
        pytest.skip("psql no está instalado")
    if "test" not in (urlsplit(admin).path or ""):
        pytest.fail("La base de TEST_ROLES_ADMIN_URL debe contener 'test'")

    migrator_pw, app_pw = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    resultado = ejecutar_bootstrap(admin, migrator_pw, app_pw)
    assert resultado.returncode == 0, resultado.stderr

    migrator = _con_credenciales(admin, "svc_migrator", migrator_pw)
    app = _con_credenciales(admin, "svc_app", app_pw)
    ddl = psql(
        migrator,
        sql=(
            "CREATE SCHEMA IF NOT EXISTS app;"
            "CREATE TYPE estado AS ENUM ('a','b');"
            "CREATE TABLE app.registro (id serial PRIMARY KEY, estado estado NOT NULL DEFAULT 'a', nota text);"
        ),
    )
    assert ddl.returncode == 0, ddl.stderr
    yield Entorno(admin=admin, migrator=migrator, app=app, app_password=app_pw)

    for rol in ("svc_app", "svc_migrator"):
        psql(admin, sql=f"DROP OWNED BY {rol}")
    psql(admin, sql="DROP ROLE IF EXISTS svc_app")
    psql(admin, sql="DROP ROLE IF EXISTS svc_migrator")


def test_app_puede_select_insert_y_update(entorno: Entorno) -> None:
    r = psql(
        entorno.app,
        sql=(
            "INSERT INTO registro (nota) VALUES ('hola');"
            "UPDATE registro SET nota = 'adios' WHERE nota = 'hola';"
            "SELECT nota FROM registro;"
        ),
    )
    assert r.returncode == 0, r.stderr
    assert "adios" in r.stdout


@pytest.mark.parametrize(
    "sentencia",
    [
        "DELETE FROM registro",
        "TRUNCATE registro",
        "DROP TABLE registro",
        "ALTER TABLE registro ADD COLUMN extra int",
        "CREATE TABLE app.intruso (i int)",
        "CREATE TABLE public.intruso (i int)",
    ],
)
def test_app_no_puede_borrar_ni_alterar(entorno: Entorno, sentencia: str) -> None:
    r = psql(entorno.app, sql=sentencia)
    assert r.returncode != 0, f"svc_app pudo ejecutar: {sentencia}"
    assert "permission denied" in r.stderr or "must be owner" in r.stderr


def test_tabla_creada_despues_hereda_solo_select_insert_update(entorno: Entorno) -> None:
    creada = psql(entorno.migrator, sql="CREATE TABLE app.futura (id serial PRIMARY KEY, v text)")
    assert creada.returncode == 0, creada.stderr
    assert psql(entorno.app, sql="INSERT INTO futura (v) VALUES ('x'); UPDATE futura SET v = 'y'").returncode == 0
    assert psql(entorno.app, sql="DELETE FROM futura").returncode != 0


def test_el_migrador_si_puede_hacer_ddl_y_borrar(entorno: Entorno) -> None:
    assert psql(entorno.migrator, sql="ALTER TABLE app.registro ADD COLUMN extra int").returncode == 0
    assert psql(entorno.migrator, sql="DELETE FROM app.registro").returncode == 0


def test_la_api_usa_el_esquema_app_por_defecto(entorno: Entorno) -> None:
    r = psql(entorno.app, sql="SHOW search_path")
    assert r.stdout.strip() == "app"
    assert psql(entorno.app, sql="SHOW statement_timeout").stdout.strip() == "5s"


def test_script_idempotente_y_rota_la_contrasena(entorno: Entorno) -> None:
    consulta = "SELECT rolpassword FROM pg_authid WHERE rolname = 'svc_app'"
    antes = psql(entorno.admin, sql=consulta).stdout.strip()
    assert antes.startswith("SCRAM-SHA-256$")  # nunca se guarda en claro

    nueva_app = secrets.token_urlsafe(36)
    migrator_pw = urlsplit(entorno.migrator).password or ""
    r = ejecutar_bootstrap(entorno.admin, migrator_pw, nueva_app)
    assert r.returncode == 0, r.stderr

    # Se compara el verificador guardado: no depende del método de autenticación del pg_hba
    assert psql(entorno.admin, sql=consulta).stdout.strip() != antes
    assert psql(_con_credenciales(entorno.admin, "svc_app", nueva_app), sql="SELECT 1").returncode == 0


def test_contrasenas_cortas_o_ausentes_abortan(entorno: Entorno) -> None:
    corta = ejecutar_bootstrap(entorno.admin, "corta", secrets.token_urlsafe(36))
    assert corta.returncode != 0
    sin_variables = psql(entorno.admin, "-f", str(SQL))
    assert sin_variables.returncode != 0
