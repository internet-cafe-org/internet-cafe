"""Pruebas de privilegios del rol `svc_app` contra el esquema real del MVP (SEC-10).

Verifica el principio de mínimo privilegio sobre las tablas reales creadas por
Alembic: `svc_app` puede operar el flujo normal (SELECT, INSERT, UPDATE), tiene
prohibido todo DDL, DELETE y TRUNCATE, y sobre `app.audit_log` únicamente puede
insertar (append-only: sin UPDATE ni DELETE).
"""

import os
import secrets
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parents
SQL_BOOTSTRAP = BACKEND_DIR / "db" / "bootstrap_roles.sql"
DB_AISLADA = "internet_cafe_sec10_test"


@dataclass
class EntornoPrivilegios:
    admin: str
    migrator: str
    app: str


def _con_credenciales(url: str, usuario: str, contrasena: str, db_name: str | None = None) -> str:
    partes = urlsplit(url)
    host = partes.hostname or "localhost"
    puerto = f":{partes.port}" if partes.port else ""
    ruta = f"/{db_name}" if db_name else partes.path
    return urlunsplit((partes.scheme, f"{usuario}:{contrasena}@{host}{puerto}", ruta, "", ""))


def _psql(url: str, *args: str, sql: str | None = None) -> subprocess.CompletedProcess:
    comando = ["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-At", *args]
    if sql is not None:
        comando += ["-c", sql]
    return subprocess.run(comando, capture_output=True, text=True, check=False)


def _es_error_de_privilegio(stderr: str) -> bool:
    texto = stderr.lower()
    return any(
        frase in texto
        for frase in ("permission denied", "must be owner", "permiso denegado", "debe ser due")
    )


@pytest.fixture(scope="module")
def entorno_mvp() -> Iterator[EntornoPrivilegios]:
    admin_base = os.environ.get("TEST_ROLES_ADMIN_URL")
    if not admin_base:
        pytest.skip("TEST_ROLES_ADMIN_URL no está definida")
    if shutil.which("psql") is None:
        pytest.skip("psql no está instalado")
    if "test" not in (urlsplit(admin_base).path or ""):
        pytest.fail("La base de TEST_ROLES_ADMIN_URL debe contener 'test'")

    partes = urlsplit(admin_base)
    admin_postgres = urlunsplit((partes.scheme, partes.netloc, "/postgres", "", ""))
    admin_aislada = urlunsplit((partes.scheme, partes.netloc, f"/{DB_AISLADA}", "", ""))

    for rol in ("svc_app", "svc_migrator"):
        _psql(admin_postgres, sql=f"DROP OWNED BY {rol}")
    _psql(admin_postgres, sql="DROP ROLE IF EXISTS svc_app")
    _psql(admin_postgres, sql="DROP ROLE IF EXISTS svc_migrator")
    _psql(admin_postgres, sql=f"DROP DATABASE IF EXISTS {DB_AISLADA}")
    creada = _psql(admin_postgres, sql=f"CREATE DATABASE {DB_AISLADA}")
    assert creada.returncode == 0, creada.stderr

    migrator_pw = secrets.token_urlsafe(36)
    app_pw = secrets.token_urlsafe(36)

    try:
        boot = _psql(
            admin_aislada,
            "-v", f"migrator_password={migrator_pw}",
            "-v", f"app_password={app_pw}",
            "-f", str(SQL_BOOTSTRAP),
        )
        assert boot.returncode == 0, boot.stderr

        migrator_url = _con_credenciales(admin_aislada, "svc_migrator", migrator_pw)
        app_url = _con_credenciales(admin_aislada, "svc_app", app_pw)

        env_alembic = os.environ.copy()
        env_alembic["DATABASE_URL"] = migrator_url
        env_alembic["DATABASE_URL_MIGRATOR"] = migrator_url
        env_alembic.setdefault("SECRET_KEY", "clave-ficticia-solo-para-pruebas-sec10")

        mig = subprocess.run(
            [shutil.which("alembic") or "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env_alembic,
            capture_output=True,
            text=True,
            check=False,
        )
        assert mig.returncode == 0, f"Fallo alembic upgrade head:\n{mig.stderr}"

        yield EntornoPrivilegios(admin=admin_aislada, migrator=migrator_url, app=app_url)
    finally:
        _psql(admin_postgres, sql=f"DROP DATABASE IF EXISTS {DB_AISLADA} WITH (FORCE)")
        for rol in ("svc_app", "svc_migrator"):
            _psql(admin_postgres, sql=f"DROP OWNED BY {rol}")
        _psql(admin_postgres, sql="DROP ROLE IF EXISTS svc_app")
        _psql(admin_postgres, sql="DROP ROLE IF EXISTS svc_migrator")


def test_app_opera_select_insert_y_update_en_tablas_mvp(entorno_mvp: EntornoPrivilegios) -> None:
    lab_id = str(uuid.uuid4())
    r = _psql(
        entorno_mvp.app,
        sql=(
            f"INSERT INTO app.labs (id, name, building, created_at) "
            f"VALUES ('{lab_id}', 'Lab SEC10', 'Bloque A', NOW());"
            f"UPDATE app.labs SET building = 'Bloque B' WHERE id = '{lab_id}';"
            f"SELECT building FROM app.labs WHERE id = '{lab_id}';"
        ),
    )
    assert r.returncode == 0, r.stderr
    assert "Bloque B" in r.stdout


@pytest.mark.parametrize(
    "sentencia",
    [
        "DELETE FROM app.labs",
        "TRUNCATE TABLE app.labs",
        "DROP TABLE app.labs",
        "ALTER TABLE app.labs ADD COLUMN columna_intrusa text",
        "CREATE TABLE app.tabla_intrusa (id int)",
        "CREATE TABLE public.tabla_intrusa (id int)",
        "DROP SCHEMA app",
    ],
)
def test_app_tiene_prohibido_ddl_delete_y_truncate(
    entorno_mvp: EntornoPrivilegios,
    sentencia: str,
) -> None:
    r = _psql(entorno_mvp.app, sql=sentencia)
    assert r.returncode != 0, f"svc_app pudo ejecutar sentencia prohibida: {sentencia}"
    assert _es_error_de_privilegio(r.stderr), r.stderr


def test_audit_log_es_solo_insert_para_app(entorno_mvp: EntornoPrivilegios) -> None:
    ins = _psql(
        entorno_mvp.app,
        sql=(
            "INSERT INTO app.audit_log (actor_type, action, created_at) "
            "VALUES ('system', 'sec10.privilege_check', NOW()) RETURNING id;"
        ),
    )
    assert ins.returncode == 0, f"svc_app debería poder insertar en audit_log: {ins.stderr}"
    audit_id = int(ins.stdout.strip().splitlines()[-1])

    upd = _psql(
        entorno_mvp.app,
        sql=f"UPDATE app.audit_log SET action = 'tampered' WHERE id = {audit_id};",
    )
    assert upd.returncode != 0, "svc_app NO debe poder hacer UPDATE en app.audit_log"
    assert _es_error_de_privilegio(upd.stderr), upd.stderr

    dele = _psql(
        entorno_mvp.app,
        sql=f"DELETE FROM app.audit_log WHERE id = {audit_id};",
    )
    assert dele.returncode != 0, "svc_app NO debe poder hacer DELETE en app.audit_log"
    assert _es_error_de_privilegio(dele.stderr), dele.stderr

    trunc = _psql(entorno_mvp.app, sql="TRUNCATE TABLE app.audit_log;")
    assert trunc.returncode != 0, "svc_app NO debe poder hacer TRUNCATE en app.audit_log"
    assert _es_error_de_privilegio(trunc.stderr), trunc.stderr

