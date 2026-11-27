"""ST-SEC-01: tabla email_codes (OTP de verificacion y recuperacion).

Revision ID: 9b4e6d1c2a7f
Revises: 7c2d4f9a1b3e
Create Date: 2026-11-26 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b4e6d1c2a7f"
down_revision: str | Sequence[str] | None = "7c2d4f9a1b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea el tipo emailcodepurpose y la tabla email_codes."""
    purpose = postgresql.ENUM(
        "verify_email",
        "reset_password",
        name="emailcodepurpose",
        schema="app",
        create_type=False,
    )
    purpose.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "email_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", purpose, nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_email_codes_user_purpose", "email_codes", ["user_id", "purpose"], schema="app"
    )


def downgrade() -> None:
    """Elimina la tabla y el tipo."""
    op.drop_index("ix_email_codes_user_purpose", table_name="email_codes", schema="app")
    op.drop_table("email_codes", schema="app")
    op.execute("DROP TYPE IF EXISTS app.emailcodepurpose")