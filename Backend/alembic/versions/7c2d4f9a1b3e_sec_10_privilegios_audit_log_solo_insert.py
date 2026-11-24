"""SEC-10: revocar UPDATE en app.audit_log para svc_app (solo INSERT).

Revision ID: 7c2d4f9a1b3e
Revises: 5e1a9c3b7d20
Create Date: 2026-11-22 18:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c2d4f9a1b3e"
down_revision: str | Sequence[str] | None = "5e1a9c3b7d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restringe app.audit_log a solo INSERT/SELECT para svc_app si el rol existe."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_app') THEN
                REVOKE UPDATE, DELETE, TRUNCATE ON TABLE app.audit_log FROM svc_app;
                GRANT INSERT, SELECT ON TABLE app.audit_log TO svc_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Restaura UPDATE en app.audit_log para svc_app si el rol existe."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_app') THEN
                GRANT UPDATE ON TABLE app.audit_log TO svc_app;
            END IF;
        END
        $$;
        """
    )
