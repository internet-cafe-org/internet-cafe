"""ST-SEC-05: aislamiento por RLS contra PostgreSQL real (SRS §12.8, HU-27).

Crea una base aislada con los roles (``bootstrap_roles.sql``) y las migraciones,
carga dos estudiantes y dos equipos con sus sesiones, retos y refresh tokens, y
comprueba qué ve cada rol según las variables ``app.*``:

- Sin variables, svc_web y svc_machine ven cero filas (falla cerrada).
- Con ``app.user_id`` / ``app.machine_id`` solo ven lo propio.
- svc_admin y svc_jobs ven todo.

Corre solo con ``TEST_ROLES_ADMIN_URL`` y ``psql``, igual que las pruebas de SEC-10.
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
DB_AISLADA = "internet_cafe_st_sec05_test"
ROLES = ("svc_web", "svc_machine", "svc_admin", "svc_jobs", "svc_app", "svc_migrator")

# Datos fijos: Ana usa PC-01 y Beto usa PC-02.
ANA = "00000000-0000-0000-0000-0000000000a1"
BETO = "00000000-0000-0000-0000-0000000000b2"
PC01 = "00000000-0000-0000-0000-000000000c01"
PC02 = "00000000-0000-0000-0000-000000000c02"
HASH_RETO_PC01 = "aa" * 32
HASH_REFRESH_ANA = "bb" * 32

DATOS = f"""
INSERT INTO app.users (id, email_ct, email_bidx, full_name_ct, password_hash, role, status,
                       privacy_consent_at, failed_login_count, created_at, updated_at)
VALUES ('{ANA}',  '\\x01', '\\x01', '\\x01', 'x', 'student', 'active', now(), 0, now(), now()),
       ('{BETO}', '\\x02', '\\x02', '\\x02', 'x', 'student', 'active', now(), 0, now(), now());
INSERT INTO app.machines (id, code, status, mode, created_at, updated_at)
VALUES ('{PC01}', 'PC-01', 'active', 'kiosk', now(), now()),
       ('{PC02}', 'PC-02', 'active', 'kiosk', now(), now());
INSERT INTO app.login_challenges (id, machine_id, token_hash, status, expires_at, created_at)
VALUES ('00000000-0000-0000-0000-0000000000d1', '{PC01}', '\\x{HASH_RETO_PC01}', 'approved', now(), now()),
       ('00000000-0000-0000-0000-0000000000d2', '{PC02}', '\\x{"cc" * 32}', 'approved', now(), now());
INSERT INTO app.access_sessions (id, user_id, machine_id, challenge_id, started_at, last_heartbeat_at)
VALUES ('00000000-0000-0000-0000-0000000000e1', '{ANA}',  '{PC01}', '00000000-0000-0000-0000-0000000000d1', now(), now()),
       ('00000000-0000-0000-0000-0000000000e2', '{BETO}', '{PC02}', '00000000-0000-0000-0000-0000000000d2', now(), now());
INSERT INTO app.refresh_tokens (id, user_id, family_id, token_hash, expires_at, created_at)
VALUES ('00000000-0000-0000-0000-0000000000f1', '{ANA}',  gen_random_uuid(), '\\x{HASH_REFRESH_ANA}', now() + interval '1 day', now()),
       ('00000000-0000-0000-0000-0000000000f2', '{BETO}', gen_random_uuid(), '\\x{"dd" * 32}', now() + interval '1 day', now());
"""


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
        entorno.setdefault("SECRET_KEY", "clave-ficticia-solo-para-pruebas-st-sec05")
        mig = subprocess.run(
            [shutil.which("alembic") or "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR), env=entorno, capture_output=True, text=True, check=False,
        )
        assert mig.returncode == 0, f"Fallo alembic upgrade head:\n{mig.stderr}"

        # Los datos los carga el dueño de las tablas, que no pasa por RLS.
        carga = _psql(resultado["svc_migrator"], sql=DATOS)
        assert carga.returncode == 0, carga.stderr
        yield resultado
    finally:
        _psql(admin_postgres, sql=f"DROP DATABASE IF EXISTS {DB_AISLADA} WITH (FORCE)")
        _borrar_roles(admin_postgres)


def _como(urls: dict[str, str], rol: str, sql: str, **variables: str) -> subprocess.CompletedProcess:
    """Ejecuta ``sql`` como ``rol`` en una transacción con las variables ``app.*`` dadas."""
    fijar = "".join(f"SET LOCAL app.{k} = '{v}';" for k, v in variables.items())
    return _psql(urls[rol], sql=f"BEGIN; {fijar} {sql}; COMMIT;")


def _filas(urls: dict[str, str], rol: str, tabla: str, **variables: str) -> list[str]:
    r = _como(urls, rol, f"SELECT id FROM app.{tabla} ORDER BY id", **variables)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


# ------------------------------------------------------------- falla cerrada (HU-27)
@pytest.mark.parametrize("rol", ["svc_web", "svc_machine"])
@pytest.mark.parametrize("tabla", ["access_sessions", "login_challenges", "refresh_tokens"])
def test_sin_variables_no_se_ve_ninguna_fila(urls: dict[str, str], rol: str, tabla: str) -> None:
    if rol == "svc_machine" and tabla == "refresh_tokens":
        pytest.skip("svc_machine no tiene GRANT sobre refresh_tokens")
    assert _filas(urls, rol, tabla) == []


def test_sin_variables_el_equipo_no_puede_actualizar_ningun_equipo(urls: dict[str, str]) -> None:
    r = _como(urls, "svc_machine", "UPDATE app.machines SET last_seen_at = now() RETURNING id")
    assert r.returncode == 0, r.stderr
    assert "-" not in r.stdout, "actualizó filas sin app.machine_id"


# ------------------------------------------------------------------------- svc_web
def test_el_estudiante_solo_ve_sus_sesiones_y_tokens(urls: dict[str, str]) -> None:
    assert _filas(urls, "svc_web", "access_sessions", user_id=ANA) == [
        "00000000-0000-0000-0000-0000000000e1"
    ]
    assert _filas(urls, "svc_web", "refresh_tokens", user_id=ANA) == [
        "00000000-0000-0000-0000-0000000000f1"
    ]


def test_el_estudiante_no_puede_cerrar_la_sesion_de_otro(urls: dict[str, str]) -> None:
    r = _como(urls, "svc_web",
              f"UPDATE app.access_sessions SET ended_at = now() WHERE user_id = '{BETO}' RETURNING id",
              user_id=ANA)
    assert r.returncode == 0, r.stderr
    assert "0000000000e2" not in r.stdout


def test_el_estudiante_no_puede_crear_sesiones_a_nombre_de_otro(urls: dict[str, str]) -> None:
    r = _como(urls, "svc_web",
              "INSERT INTO app.access_sessions (id, user_id, machine_id, challenge_id, started_at, "
              f"last_heartbeat_at) VALUES (gen_random_uuid(), '{BETO}', '{PC01}', "
              "'00000000-0000-0000-0000-0000000000d1', now(), now())",
              user_id=ANA)
    assert r.returncode != 0
    assert "row-level security" in r.stderr


def test_el_refresh_presentado_solo_deja_ver_ese_token(urls: dict[str, str]) -> None:
    assert _filas(urls, "svc_web", "refresh_tokens", refresh_hash=HASH_REFRESH_ANA) == [
        "00000000-0000-0000-0000-0000000000f1"
    ]


def test_el_qr_escaneado_solo_deja_ver_ese_reto(urls: dict[str, str]) -> None:
    assert _filas(urls, "svc_web", "login_challenges", challenge_hash=HASH_RETO_PC01) == [
        "00000000-0000-0000-0000-0000000000d1"
    ]


def test_la_web_bloquea_equipos_pero_no_los_modifica(urls: dict[str, str]) -> None:
    bloqueo = _como(urls, "svc_web", f"SELECT id FROM app.machines WHERE id = '{PC01}' FOR UPDATE")
    assert bloqueo.returncode == 0, bloqueo.stderr
    escritura = _como(urls, "svc_web", "UPDATE app.machines SET updated_at = now()")
    assert escritura.returncode != 0
    assert "row-level security" in escritura.stderr


# --------------------------------------------------------------------- svc_machine
def test_el_equipo_solo_ve_sus_sesiones_y_retos(urls: dict[str, str]) -> None:
    assert _filas(urls, "svc_machine", "access_sessions", machine_id=PC01) == [
        "00000000-0000-0000-0000-0000000000e1"
    ]
    assert _filas(urls, "svc_machine", "login_challenges", machine_id=PC01) == [
        "00000000-0000-0000-0000-0000000000d1"
    ]


def test_el_equipo_solo_actualiza_su_fila(urls: dict[str, str]) -> None:
    r = _como(urls, "svc_machine", "UPDATE app.machines SET last_seen_at = now() RETURNING code",
              machine_id=PC01)
    assert r.returncode == 0, r.stderr
    assert "PC-01" in r.stdout and "PC-02" not in r.stdout


def test_el_equipo_ve_el_historial_solo_del_estudiante_sentado(urls: dict[str, str]) -> None:
    vistas = _filas(urls, "svc_machine", "access_sessions", machine_id=PC02, machine_user_id=ANA)
    assert set(vistas) == {"00000000-0000-0000-0000-0000000000e1", "00000000-0000-0000-0000-0000000000e2"}
    # Beto no está sentado en PC-01: PC-01 no ve sus sesiones
    assert _filas(urls, "svc_machine", "access_sessions", machine_id=PC01) == [
        "00000000-0000-0000-0000-0000000000e1"
    ]


# ------------------------------------------------------------------ sin restricción
@pytest.mark.parametrize("rol", ["svc_admin", "svc_jobs", "svc_app"])
def test_admin_tareas_y_el_rol_de_transicion_ven_todo(urls: dict[str, str], rol: str) -> None:
    assert len(_filas(urls, rol, "access_sessions")) == 2
