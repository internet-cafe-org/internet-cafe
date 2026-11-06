"""Modelos de Base de Datos para el Sistema de Registro de Acceso por QR.

Define las tablas finales del MVP según el SRS-IC-001 (Sección 11.2).
Utiliza SQLAlchemy 2.0 y ubica las tablas en el esquema 'app' exigido por el SRS.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime, LargeBinary, Enum, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
import enum

# Esquema exigido por el SRS (Sección 11)
SCHEMA_NAME = "app"

# ==========================================
# 1. TIPOS ENUMERADOS (SRS Sección 11.3)
# ==========================================
class UserRole(str, enum.Enum):
    student = "student"
    admin = "admin"

class UserStatus(str, enum.Enum):
    pending_verification = "pending_verification"
    active = "active"
    blocked = "blocked"

class MachineStatus(str, enum.Enum):
    pending_enrollment = "pending_enrollment"
    active = "active"
    disabled = "disabled"

class MachineMode(str, enum.Enum):
    passive = "passive"
    kiosk = "kiosk"

class ChallengeStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    expired = "expired"
    cancelled = "cancelled"

class SessionEndReason(str, enum.Enum):
    user_logout_pc = "user_logout_pc"
    user_logout_web = "user_logout_web"
    superseded = "superseded"
    heartbeat_timeout = "heartbeat_timeout"
    admin_forced = "admin_forced"
    machine_shutdown = "machine_shutdown"

class AuditActorType(str, enum.Enum):
    user = "user"
    machine = "machine"
    system = "system"

# ==========================================
# 2. MODELOS (SRS Sección 11.2)
# ==========================================

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_bidx: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    student_code_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    student_code_bidx: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=True)
    full_name_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.student, nullable=False)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.pending_verification, nullable=False)
    email_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class Lab(Base):
    __tablename__ = "labs"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    building: Mapped[str] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Machine(Base):
    __tablename__ = "machines"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.labs.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(63), nullable=True)
    status: Mapped[MachineStatus] = mapped_column(Enum(MachineStatus), default=MachineStatus.pending_enrollment, nullable=False)
    mode: Mapped[MachineMode] = mapped_column(Enum(MachineMode), default=MachineMode.passive, nullable=False)
    public_key_jwk: Mapped[dict] = mapped_column(JSONB, nullable=True)
    key_thumbprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=True)
    app_version: Mapped[str] = mapped_column(String(20), nullable=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class LoginChallenge(Base):
    __tablename__ = "login_challenges"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.machines.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    status: Mapped[ChallengeStatus] = mapped_column(Enum(ChallengeStatus), default=ChallengeStatus.pending, nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class AccessSession(Base):
    __tablename__ = "access_sessions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"), nullable=False)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.machines.id"), nullable=False)
    challenge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.login_challenges.id"), unique=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[SessionEndReason] = mapped_column(Enum(SessionEndReason), nullable=True)

    __table_args__ = (
        CheckConstraint('(ended_at IS NULL) = (end_reason IS NULL)', name='check_ended_reason'),
        CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name='check_ended_after_started'),
        Index('uq_active_session_per_machine', 'machine_id', unique=True, postgresql_where=(ended_at.is_(None))),
        Index('uq_active_session_per_user', 'user_id', unique=True, postgresql_where=(ended_at.is_(None))),
        {"schema": SCHEMA_NAME}
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[AuditActorType] = mapped_column(Enum(AuditActorType), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_info: Mapped[dict] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.refresh_tokens.id"), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.machines.id"), nullable=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"), nullable=False)
    template: Mapped[str] = mapped_column(String, nullable=False)
    to_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)