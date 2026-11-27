"""ST-SEC-03: un rol de base de datos por actor (SRS §12.8). Pruebas sin base de datos.

Revisa tres cosas: que cada ruta use la conexión de su actor, que la matriz de
privilegios de la migración respete el mínimo privilegio y que el bootstrap cree
los cuatro roles con sus límites.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from app import database

BACKEND = Path(__file__).resolve().parents[2]
MIGRACION = BACKEND / "alembic" / "versions" / "9b4e6d2a8c15_st_sec_03_privilegios_por_actor.py"
SQL = (BACKEND / "db" / "bootstrap_roles.sql").read_text(encoding="utf-8")
CODIGO_SQL = "\n".join(linea.split("--", 1)[0] for linea in SQL.splitlines())

ROLES = ("svc_web", "svc_machine", "svc_admin", "svc_jobs")
TABLAS_EFIMERAS = {"login_challenges", "refresh_tokens", "enrollment_codes", "email_outbox"}


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location("st_sec_03", MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


MIG = _cargar_migracion()


def _privilegios(rol: str, tabla: str) -> str:
    return next((p for t, p in MIG.PRIVILEGIOS[rol] if t == tabla), "")


# ----------------------------------------------------------------- rutas y motores
@pytest.mark.parametrize(
    ("ruta", "actor"),
    [
        ("/api/v1/auth/login", "web"),
        ("/api/v1/me/sessions", "web"),
        ("/api/v1/scan/claim", "web"),
        ("/readyz", "web"),
        ("/api/v1/machine/heartbeat", "maquina"),
        ("/api/v1/machine/challenges/wait", "maquina"),
        ("/api/v1/admin/sessions", "admin"),
        ("/api/v1/admin/machines/123", "admin"),
        # Un prefijo parecido no cambia de actor
        ("/api/v1/machines", "web"),
        ("/api/v1/administrador", "web"),
    ],
)
def test_cada_ruta_usa_la_conexion_de_su_actor(ruta: str, actor: str) -> None:
    assert database.actor_de_ruta(ruta) == actor


def test_sin_url_propia_el_actor_usa_el_motor_por_defecto() -> None:
    assert database._motor_de(None, 5) is database.motor_async
    assert database._motor_de("", 5) is database.motor_async


def test_actores_con_la_misma_url_comparten_motor() -> None:
    url = "postgresql://svc_web:x@localhost:5432/una_base_test"
    try:
        primero = database._motor_de(url, 5)
        assert database._motor_de(url, 2) is primero
        assert primero is not database.motor_async
    finally:
        database._motores_por_url.pop(url, None)


def test_hay_una_fabrica_por_actor() -> None:
    assert set(database.fabricas) == {"web", "maquina", "admin", "tareas"}


# ------------------------------------------------------------- matriz de privilegios
def test_la_migracion_sigue_a_sec_10() -> None:
    assert MIG.down_revision == "7c2d4f9a1b3e"


def test_la_matriz_cubre_los_cuatro_roles() -> None:
    assert set(MIG.PRIVILEGIOS) == set(ROLES)


@pytest.mark.parametrize("rol", ROLES)
def test_ningun_rol_recibe_privilegios_peligrosos(rol: str) -> None:
    for tabla, privs in MIG.PRIVILEGIOS[rol]:
        for prohibido in ("TRUNCATE", "REFERENCES", "TRIGGER", "ALL"):
            assert not re.search(rf"\b{prohibido}\b", privs), (rol, tabla, privs)


@pytest.mark.parametrize("rol", ["svc_web", "svc_machine", "svc_admin"])
def test_solo_svc_jobs_puede_borrar(rol: str) -> None:
    for tabla, privs in MIG.PRIVILEGIOS[rol]:
        assert "DELETE" not in privs, (rol, tabla)


def test_svc_jobs_solo_borra_tablas_efimeras() -> None:
    con_delete = {t for t, p in MIG.PRIVILEGIOS["svc_jobs"] if "DELETE" in p}
    assert con_delete <= TABLAS_EFIMERAS


@pytest.mark.parametrize("rol", ROLES)
def test_audit_log_no_se_puede_modificar(rol: str) -> None:
    privs = _privilegios(rol, "audit_log")
    assert "INSERT" in privs
    assert "UPDATE" not in privs and "DELETE" not in privs


def test_admin_no_lee_password_hash() -> None:
    privs = _privilegios("svc_admin", "users")
    assert "password_hash" not in privs
    assert re.search(r"SELECT \(", privs), "el SELECT del admin debe ser por columnas"


def test_el_equipo_solo_lee_nombre_y_codigo_del_estudiante() -> None:
    assert _privilegios("svc_machine", "users") == "SELECT (id, full_name_ct, student_code_ct)"


def test_la_web_no_lee_la_clave_ni_la_credencial_del_equipo() -> None:
    privs = _privilegios("svc_web", "machines")
    for columna in ("public_key_jwk", "key_thumbprint", "credential_hash"):
        assert columna not in privs


def test_las_columnas_que_lee_la_web_coinciden_con_el_codigo() -> None:
    from app.services.challenges import COLUMNAS_PUBLICAS_EQUIPO

    concedidas = re.search(r"SELECT \(([^)]*)\)", _privilegios("svc_web", "machines")).group(1)
    assert {c.key for c in COLUMNAS_PUBLICAS_EQUIPO} == {c.strip() for c in concedidas.split(",")}


def test_las_columnas_que_lee_el_equipo_coinciden_con_el_codigo() -> None:
    from app.services.sesiones import COLUMNAS_ESTUDIANTE

    concedidas = re.search(r"SELECT \(([^)]*)\)", _privilegios("svc_machine", "users")).group(1)
    assert {c.key for c in COLUMNAS_ESTUDIANTE} == {c.strip() for c in concedidas.split(",")}


# ------------------------------------------------------------------------ bootstrap
@pytest.mark.parametrize("rol", ROLES)
def test_el_bootstrap_crea_el_rol_con_sus_limites(rol: str) -> None:
    assert f"('{rol}'," in CODIGO_SQL
    assert re.search(rf"ALTER ROLE {rol}\s+SET statement_timeout = '5s'", CODIGO_SQL)
    assert re.search(rf"ALTER ROLE {rol}\s+SET idle_in_transaction_session_timeout = '10s'", CODIGO_SQL)
    assert re.search(rf"ALTER ROLE {rol}\s+SET search_path = app", CODIGO_SQL)


@pytest.mark.parametrize("variable", ["web_password", "machine_password", "admin_password", "jobs_password"])
def test_las_contrasenas_de_los_actores_llegan_por_psql(variable: str) -> None:
    assert f":'{variable}'" in CODIGO_SQL


def test_los_roles_de_actor_no_reciben_privilegios_por_defecto() -> None:
    # Sus GRANT viven en la migración; un privilegio por defecto los saltaría.
    for bloque in re.findall(r"ALTER DEFAULT PRIVILEGES[^;]*;", CODIGO_SQL, re.DOTALL):
        for rol in ROLES:
            assert rol not in bloque, bloque
