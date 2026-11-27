"""ST-SEC-05: políticas RLS de las tablas con dueño (SRS §12.8).

Activa Row-Level Security en ``access_sessions``, ``login_challenges``,
``refresh_tokens`` y ``machines`` (en esta última solo limita el UPDATE).
Las políticas de ``svc_web`` y ``svc_machine`` comparan con variables ``app.*``
que la API fija tras autenticar (``app/database.py:fijar_contexto_rls``). Si la
variable no está definida, la comparación da NULL y la política devuelve cero
filas: falla cerrada.

``svc_admin``, ``svc_jobs`` y ``svc_app`` (el rol único de antes de ST-SEC-03,
que siguen usando los entornos sin las URL por actor) no tienen restricción.
Los dueños de las tablas (``svc_migrator``) y los superusuarios no pasan por RLS.

Revision ID: c3a7e5f1d902
Revises: 9b4e6d2a8c15
Create Date: 2026-11-25 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a7e5f1d902"
down_revision: str | Sequence[str] | None = "9b4e6d2a8c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLAS = ("access_sessions", "login_challenges", "refresh_tokens", "machines")


def _uuid(variable: str) -> str:
    return f"nullif(current_setting('app.{variable}', true), '')::uuid"


def _hash(variable: str) -> str:
    return f"decode(nullif(current_setting('app.{variable}', true), ''), 'hex')"


USUARIO = _uuid("user_id")
EQUIPO = _uuid("machine_id")
EQUIPO_DEL_QR = _uuid("claim_machine_id")
ESTUDIANTE_DEL_EQUIPO = _uuid("machine_user_id")
HASH_REFRESH = _hash("refresh_hash")
HASH_RETO = _hash("challenge_hash")

# (nombre, tabla, rol, comando, USING, WITH CHECK). None = sin cláusula.
POLITICAS: list[tuple[str, str, str, str, str | None, str | None]] = [
    # ---------------------------------------------------------------- svc_web
    # Sus sesiones; y las del equipo del QR, para saber si está ocupado.
    ("sesiones_web_leer", "access_sessions", "svc_web", "SELECT",
     f"user_id = {USUARIO} OR machine_id = {EQUIPO_DEL_QR}", None),
    ("sesiones_web_crear", "access_sessions", "svc_web", "INSERT", None, f"user_id = {USUARIO}"),
    ("sesiones_web_cerrar", "access_sessions", "svc_web", "UPDATE",
     f"user_id = {USUARIO}", f"user_id = {USUARIO}"),
    # El reto del QR que tiene en la mano, los demás de ese equipo y los que aprobó.
    ("retos_web_leer", "login_challenges", "svc_web", "SELECT",
     f"token_hash = {HASH_RETO} OR machine_id = {EQUIPO_DEL_QR} OR approved_by = {USUARIO}", None),
    ("retos_web_resolver", "login_challenges", "svc_web", "UPDATE",
     f"token_hash = {HASH_RETO} OR machine_id = {EQUIPO_DEL_QR}",
     f"token_hash = {HASH_RETO} OR machine_id = {EQUIPO_DEL_QR}"),
    # Sus tokens; y el que presenta al renovar o cerrar sesión.
    ("refresh_web_leer", "refresh_tokens", "svc_web", "SELECT",
     f"user_id = {USUARIO} OR token_hash = {HASH_REFRESH}", None),
    ("refresh_web_crear", "refresh_tokens", "svc_web", "INSERT", None, f"user_id = {USUARIO}"),
    ("refresh_web_revocar", "refresh_tokens", "svc_web", "UPDATE",
     f"user_id = {USUARIO} OR token_hash = {HASH_REFRESH}", f"user_id = {USUARIO}"),
    # Lee todos los equipos; el UPDATE solo existe para bloquear la fila en el claim
    # (SELECT ... FOR UPDATE), así que ninguna escritura pasa el WITH CHECK.
    ("equipos_web_leer", "machines", "svc_web", "SELECT", "true", None),
    ("equipos_web_bloquear", "machines", "svc_web", "UPDATE", "true", "false"),
    # ------------------------------------------------------------ svc_machine
    # Sus sesiones; y el historial del estudiante sentado en él (últimos accesos, ST-BE-04).
    ("sesiones_equipo_leer", "access_sessions", "svc_machine", "SELECT",
     f"machine_id = {EQUIPO} OR user_id = {ESTUDIANTE_DEL_EQUIPO}", None),
    ("sesiones_equipo_actualizar", "access_sessions", "svc_machine", "UPDATE",
     f"machine_id = {EQUIPO}", f"machine_id = {EQUIPO}"),
    ("retos_equipo", "login_challenges", "svc_machine", "ALL",
     f"machine_id = {EQUIPO}", f"machine_id = {EQUIPO}"),
    ("equipos_equipo_leer", "machines", "svc_machine", "SELECT", "true", None),
    ("equipos_equipo_actualizar", "machines", "svc_machine", "UPDATE",
     f"id = {EQUIPO}", f"id = {EQUIPO}"),
]

# Roles sin RLS (SRS §12.8) más svc_app, el rol único de transición.
ROLES_SIN_RESTRICCION = ("svc_admin", "svc_jobs", "svc_app")
for _rol in ROLES_SIN_RESTRICCION:
    for _tabla in TABLAS:
        POLITICAS.append((f"{_tabla}_{_rol}_todo", _tabla, _rol, "ALL", "true", "true"))


def _crear(nombre: str, tabla: str, rol: str, comando: str, using: str | None, check: str | None) -> str:
    sentencia = f"CREATE POLICY {nombre} ON app.{tabla} AS PERMISSIVE FOR {comando} TO {rol}"
    if using is not None:
        sentencia += f" USING ({using})"
    if check is not None:
        sentencia += f" WITH CHECK ({check})"
    return sentencia


def _si_existe(rol: str, sentencia: str) -> str:
    sql = sentencia.replace("'", "''")
    return (
        "DO $$ BEGIN "
        f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rol}') THEN EXECUTE '{sql}'; "
        f"ELSE RAISE NOTICE 'ST-SEC-05: el rol {rol} no existe; se omite su política'; END IF; "
        "END $$;"
    )


def upgrade() -> None:
    """Activa RLS y crea las políticas de cada rol que exista."""
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE app.{tabla} ENABLE ROW LEVEL SECURITY")
    for politica in POLITICAS:
        op.execute(_si_existe(politica[2], _crear(*politica)))


def downgrade() -> None:
    """Quita las políticas y desactiva RLS."""
    for nombre, tabla, *_ in POLITICAS:
        op.execute(f"DROP POLICY IF EXISTS {nombre} ON app.{tabla}")
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE app.{tabla} DISABLE ROW LEVEL SECURITY")
