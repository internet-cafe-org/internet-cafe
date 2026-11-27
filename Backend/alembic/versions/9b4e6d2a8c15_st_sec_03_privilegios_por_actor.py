"""ST-SEC-03: privilegios de los cuatro roles por actor (SRS §12.8).

Concede a svc_web, svc_machine, svc_admin y svc_jobs solo lo que necesitan
sus endpoints, con GRANT por columna donde el SRS lo pide. Los roles los crea
``db/bootstrap_roles.sql``; si un rol no existe (CI, local), se omite.

Las políticas RLS no van aquí: son ST-SEC-05.

Revision ID: 9b4e6d2a8c15
Revises: 7c2d4f9a1b3e
Create Date: 2026-11-25 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b4e6d2a8c15"
down_revision: str | Sequence[str] | None = "7c2d4f9a1b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Columnas de users que el admin puede leer: todas menos password_hash.
_USERS_SIN_HASH = (
    "id, email_ct, email_bidx, student_code_ct, student_code_bidx, full_name_ct, role, "
    "status, email_verified_at, privacy_consent_at, failed_login_count, locked_until, "
    "last_login_at, created_at, updated_at"
)

# audit_log es de solo inserción. SELECT(id) hace falta porque el ORM inserta con
# RETURNING id; no permite leer ninguna otra columna del registro.
_AUDIT_SOLO_INSERT = "INSERT, SELECT (id)"

# Rol → [(tabla, privilegios)]. Solo svc_jobs tiene DELETE, y solo en tablas efímeras.
PRIVILEGIOS: dict[str, list[tuple[str, str]]] = {
    # /auth, /me, /scan
    "svc_web": [
        ("users", "SELECT, INSERT, UPDATE (password_hash, status, email_verified_at, "
                  "failed_login_count, locked_until, last_login_at, updated_at)"),
        ("refresh_tokens", "SELECT, INSERT, UPDATE (revoked_at, replaced_by)"),
        ("labs", "SELECT"),
        # UPDATE(updated_at) solo porque el claim bloquea el equipo con SELECT ... FOR
        # UPDATE (BE-05/BE-07b) y PostgreSQL exige UPDATE en alguna columna para bloquear.
        ("machines", "SELECT (id, code, lab_id, status, mode), UPDATE (updated_at)"),
        ("login_challenges", "SELECT, UPDATE (status, approved_by, approved_at)"),
        ("access_sessions", "SELECT, INSERT, UPDATE (ended_at, end_reason)"),
        ("email_outbox", "INSERT"),
        ("audit_log", _AUDIT_SOLO_INSERT),
    ],
    # /machine/*
    "svc_machine": [
        # Solo lo que muestra el tablero del equipo (nombre y código enmascarado)
        ("users", "SELECT (id, full_name_ct, student_code_ct)"),
        ("labs", "SELECT"),
        ("machines", "SELECT, UPDATE (last_seen_at, app_version, hostname, public_key_jwk, "
                     "key_thumbprint, credential_hash, status, enrolled_at, updated_at)"),
        ("enrollment_codes", "SELECT, UPDATE (used_at)"),
        ("login_challenges", "SELECT, INSERT, UPDATE (status)"),
        ("access_sessions", "SELECT, UPDATE (last_heartbeat_at, ended_at, end_reason)"),
        ("audit_log", _AUDIT_SOLO_INSERT),
    ],
    # /admin/*
    "svc_admin": [
        ("users", f"SELECT ({_USERS_SIN_HASH}), UPDATE (status, role, updated_at)"),
        ("refresh_tokens", "SELECT, UPDATE (revoked_at)"),
        ("labs", "SELECT, INSERT, UPDATE"),
        # enrolled_at: revocar la clave deja el equipo para enrolarlo de nuevo (BE-13)
        ("machines", "SELECT, INSERT, UPDATE (lab_id, mode, status, public_key_jwk, "
                     "key_thumbprint, credential_hash, enrolled_at, updated_at)"),
        # UPDATE(used_at): al generar un código nuevo se invalidan los anteriores (BE-13)
        ("enrollment_codes", "SELECT, INSERT, UPDATE (used_at)"),
        # UPDATE(status): deshabilitar un equipo cancela sus retos pendientes (BE-12)
        ("login_challenges", "SELECT, UPDATE (status)"),
        ("access_sessions", "SELECT, UPDATE (ended_at, end_reason)"),
        ("audit_log", "SELECT, INSERT"),
    ],
    # Barrido de inactividad, expiración, outbox y limpieza
    "svc_jobs": [
        ("access_sessions", "SELECT, UPDATE (ended_at, end_reason)"),
        ("login_challenges", "SELECT, UPDATE (status), DELETE"),
        ("refresh_tokens", "SELECT, DELETE"),
        ("enrollment_codes", "SELECT, DELETE"),
        ("email_outbox", "SELECT, UPDATE (status, attempts, next_attempt_at, last_error, "
                         "provider_message_id, sent_at, payload_ct), DELETE"),
        ("audit_log", _AUDIT_SOLO_INSERT),
    ],
}

# Roles que insertan en audit_log: el id sale de una secuencia.
_USAN_SECUENCIA_AUDIT = ("svc_web", "svc_machine", "svc_admin", "svc_jobs")


def _si_existe(rol: str, sentencias: list[str]) -> str:
    """Envuelve sentencias en un bloque que solo corre si el rol existe.

    Args:
        rol: Nombre del rol de PostgreSQL.
        sentencias: Sentencias SQL sin punto y coma final.

    Returns:
        Bloque ``DO`` listo para ``op.execute``.
    """
    cuerpo = "\n".join(f"        {s};" for s in sentencias)
    return f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rol}') THEN
{cuerpo}
        ELSE
            RAISE NOTICE 'ST-SEC-03: el rol {rol} no existe; se omiten sus privilegios';
        END IF;
    END
    $$;
    """


def _revocar_todo(rol: str) -> list[str]:
    """Sentencias que dejan al rol sin privilegios sobre el esquema app.

    Args:
        rol: Nombre del rol.

    Returns:
        Lista de sentencias REVOKE.
    """
    return [
        f"REVOKE ALL ON ALL TABLES IN SCHEMA app FROM {rol}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM {rol}",
    ]


def upgrade() -> None:
    """Concede a cada rol de actor exactamente su fila de la matriz del SRS."""
    for rol, permisos in PRIVILEGIOS.items():
        sentencias = _revocar_todo(rol)
        sentencias += [f"GRANT {privs} ON TABLE app.{tabla} TO {rol}" for tabla, privs in permisos]
        if rol in _USAN_SECUENCIA_AUDIT:
            sentencias.append(f"GRANT USAGE ON SEQUENCE app.audit_log_id_seq TO {rol}")
        op.execute(_si_existe(rol, sentencias))


def downgrade() -> None:
    """Retira los privilegios de los roles de actor (los roles no se borran)."""
    for rol in PRIVILEGIOS:
        op.execute(_si_existe(rol, _revocar_todo(rol)))
