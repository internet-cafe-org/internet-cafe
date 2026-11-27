"""ST-SEC-03: privilegios de los cuatro roles por actor contra PostgreSQL real.

Crea una base aislada, corre ``db/bootstrap_roles.sql`` con las seis contraseñas y
``alembic upgrade head`` con svc_migrator, y comprueba qué puede y qué no puede
hacer cada rol (SRS §12.8). Las sentencias usan ``WHERE false``: PostgreSQL revisa
los privilegios al planear la consulta, así que no hacen falta datos.

Corre solo con ``TEST_ROLES_ADMIN_URL`` (superusuario y una base con "test" en el
nombre) y el cliente ``psql``, igual que las pruebas de SEC-10.
"""

import os
import secrets
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
SQL_BOOTSTRAP = BACKEND_DIR / "db" / "bootstrap_roles.sql"
DB_AISLADA = "internet_cafe_st_sec03_test"
ROLES = ("svc_web", "svc_machine", "svc_admin", "svc_jobs", "svc_app", "svc_migrator")
ACTORES = ("svc_web", "svc_machine", "svc_admin", "svc_jobs")


def _con_credenciales(url: str, usuario: str, contrasena: str) -> str:
    partes = urlsplit(url)
    host = partes.hostname or "localhost"
    puerto = f":{partes.port}" if partes.port else ""
    return urlunsplit((partes.scheme, f"{usuario}:{contrasena}@{host}{puerto}", partes.path, "", ""))


def _psql(url: str, *args: str, sql: str | None = None) -> subprocess.CompletedProcess:
    comando = ["psql", url, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-At", *args]
    if sql is not None:
        comando += ["-c", sql]
    return subprocess.run(comando, capture_output=True, encoding="utf-8", errors="replace", check=False)


def _es_error_de_privilegio(stderr: str) -> bool:
    texto = (stderr or "").lower()
    return any(f in texto for f in ("permission denied", "must be owner", "permiso denegado", "debe ser due"))


def _borrar_roles(admin_postgres: str) -> None:
    for rol in ROLES:
        _psql(admin_postgres, sql=f"DROP OWNED BY {rol}")
        _psql(admin_postgres, sql=f"DROP ROLE IF EXISTS {rol}")


@pytest.fixture(scope="module")
def urls() -> Iterator[dict[str, str]]:
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

    _psql(admin_postgres, sql=f"DROP DATABASE IF EXISTS {DB_AISLADA} WITH (FORCE)")
    _borrar_roles(admin_postgres)
    creada = _psql(admin_postgres, sql=f"CREATE DATABASE {DB_AISLADA}")
    assert creada.returncode == 0, creada.stderr

    claves = {rol: secrets.token_urlsafe(36) for rol in ROLES}
    try:
        boot = _psql(
            admin_aislada,
            "-v", f"migrator_password={claves['svc_migrator']}",
            "-v", f"app_password={claves['svc_app']}",
            "-v", f"web_password={claves['svc_web']}",
            "-v", f"machine_password={claves['svc_machine']}",
            "-v", f"admin_password={claves['svc_admin']}",
            "-v", f"jobs_password={claves['svc_jobs']}",
            "-f", str(SQL_BOOTSTRAP),
        )
        assert boot.returncode == 0, boot.stderr

        resultado = {rol: _con_credenciales(admin_aislada, rol, clave) for rol, clave in claves.items()}
        entorno = os.environ.copy()
        entorno["DATABASE_URL"] = resultado["svc_migrator"]
        entorno["DATABASE_URL_MIGRATOR"] = resultado["svc_migrator"]
        entorno.setdefault("SECRET_KEY", "clave-ficticia-solo-para-pruebas-st-sec03")
        mig = subprocess.run(
            [shutil.which("alembic") or "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        assert mig.returncode == 0, f"Fallo alembic upgrade head:\n{mig.stderr}"

        resultado["admin"] = admin_aislada
        yield resultado
    finally:
        _psql(admin_postgres, sql=f"DROP DATABASE IF EXISTS {DB_AISLADA} WITH (FORCE)")
        _borrar_roles(admin_postgres)


PERMITIDAS = [
    ("svc_web", "SELECT password_hash, status FROM app.users WHERE false"),
    ("svc_web", "UPDATE app.users SET failed_login_count = 0 WHERE false"),
    ("svc_web", "SELECT id, code, lab_id, status, mode FROM app.machines WHERE false FOR UPDATE"),
    ("svc_web", "INSERT INTO app.audit_log (actor_type, action, created_at) "
                "VALUES ('system', 'st_sec03.prueba', NOW())"),
    ("svc_machine", "SELECT full_name_ct, student_code_ct FROM app.users WHERE false"),
    ("svc_machine", "UPDATE app.machines SET last_seen_at = NOW() WHERE false"),
    ("svc_machine", "UPDATE app.access_sessions SET last_heartbeat_at = NOW() WHERE false"),
    ("svc_admin", "SELECT email_ct, status, role FROM app.users WHERE false"),
    ("svc_admin", "UPDATE app.users SET status = 'blocked' WHERE false"),
    ("svc_admin", "SELECT * FROM app.audit_log WHERE false"),
    ("svc_jobs", "DELETE FROM app.refresh_tokens WHERE false"),
    ("svc_jobs", "UPDATE app.access_sessions SET ended_at = NOW() WHERE false"),
]

PROHIBIDAS = [
    # Nadie más que svc_jobs borra, y svc_jobs solo en tablas efímeras
    ("svc_web", "DELETE FROM app.refresh_tokens WHERE false"),
    ("svc_machine", "DELETE FROM app.access_sessions WHERE false"),
    ("svc_admin", "DELETE FROM app.labs WHERE false"),
    ("svc_jobs", "DELETE FROM app.users WHERE false"),
    ("svc_jobs", "DELETE FROM app.audit_log WHERE false"),
    # Columnas que el SRS reserva
    ("svc_admin", "SELECT password_hash FROM app.users WHERE false"),
    ("svc_admin", "UPDATE app.users SET password_hash = 'x' WHERE false"),
    ("svc_machine", "SELECT password_hash FROM app.users WHERE false"),
    ("svc_machine", "SELECT email_ct FROM app.users WHERE false"),
    ("svc_machine", "UPDATE app.users SET status = 'blocked' WHERE false"),
    ("svc_web", "SELECT credential_hash FROM app.machines WHERE false"),
    ("svc_web", "UPDATE app.machines SET status = 'disabled' WHERE false"),
    ("svc_jobs", "SELECT id FROM app.users WHERE false"),
    # audit_log solo admite inserciones
    ("svc_web", "UPDATE app.audit_log SET action = 'x' WHERE false"),
    ("svc_web", "SELECT action FROM app.audit_log WHERE false"),
]


@pytest.mark.parametrize(("rol", "sentencia"), PERMITIDAS)
def test_cada_rol_puede_lo_que_necesita(urls: dict[str, str], rol: str, sentencia: str) -> None:
    r = _psql(urls[rol], sql=sentencia)
    assert r.returncode == 0, f"{rol} debería poder: {sentencia}\n{r.stderr}"


@pytest.mark.parametrize(("rol", "sentencia"), PROHIBIDAS)
def test_cada_rol_tiene_prohibido_lo_demas(urls: dict[str, str], rol: str, sentencia: str) -> None:
    r = _psql(urls[rol], sql=sentencia)
    assert r.returncode != 0, f"{rol} NO debería poder: {sentencia}"
    assert _es_error_de_privilegio(r.stderr), r.stderr


@pytest.mark.parametrize("rol", ACTORES)
@pytest.mark.parametrize(
    "sentencia",
    ["CREATE TABLE app.intrusa (id int)", "TRUNCATE TABLE app.labs", "DROP TABLE app.labs"],
)
def test_ningun_actor_hace_ddl_ni_truncate(urls: dict[str, str], rol: str, sentencia: str) -> None:
    r = _psql(urls[rol], sql=sentencia)
    assert r.returncode != 0, f"{rol} pudo ejecutar: {sentencia}"
    assert _es_error_de_privilegio(r.stderr), r.stderr


@pytest.mark.parametrize("rol", ACTORES)
def test_los_roles_de_actor_tienen_los_atributos_del_srs(urls: dict[str, str], rol: str) -> None:
    r = _psql(
        urls["admin"],
        sql=(
            "SELECT rolsuper, rolinherit, rolcreatedb, rolcreaterole, rolbypassrls, "
            f"array_to_string(rolconfig, ',') FROM pg_roles WHERE rolname = '{rol}'"
        ),
    )
    assert r.returncode == 0, r.stderr
    superu, hereda, createdb, createrole, bypass, config = r.stdout.strip().split("|")
    assert (superu, hereda, createdb, createrole, bypass) == ("f", "f", "f", "f", "f")
    assert "statement_timeout=5s" in config
    assert "idle_in_transaction_session_timeout=10s" in config
