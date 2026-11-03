"""Fixtures de integración contra PostgreSQL real (QA-05).

Las pruebas de concurrencia necesitan `FOR UPDATE` y los índices únicos
parciales, así que no sirven con mocks. La conexión sale solo de la variable
`TEST_DATABASE_URL`; si no está, las pruebas se saltan. Por seguridad, el
nombre de la base debe contener "test", porque cada prueba hace TRUNCATE.
"""

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401  (registra las tablas en Base.metadata)
from app.database import Base
from app.models import Lab, Machine, MachineStatus, User, UserRole, UserStatus
from app.services import events

TABLAS = ", ".join(f"app.{t.name}" for t in Base.metadata.sorted_tables)


def _url_de_prueba() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no está definida")
    nombre = make_url(url).database or ""
    if "test" not in nombre:
        pytest.fail(f"La base '{nombre}' no parece de pruebas; se evita el TRUNCATE")
    return url


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    """Motor sin pool (cada sesión es una conexión real) con el esquema creado."""
    engine = create_async_engine(_url_de_prueba(), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        await conn.run_sync(Base.metadata.create_all)
    events.reset_events()
    yield engine
    events.reset_events()
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLAS} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def sesiones(motor: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(motor, expire_on_commit=False)


@dataclass
class Datos:
    lab: Lab
    pc01: Machine
    pc02: Machine
    ana: User
    beto: User


def _estudiante(n: int) -> User:
    # Datos ficticios: no son personas reales ni van cifrados en esta prueba
    return User(
        email_ct=f"estudiante{n}@test.invalid".encode(),
        email_bidx=uuid.uuid4().bytes,
        full_name_ct=f"Estudiante Prueba {n}".encode(),
        student_code_ct=f"000000000{n}".encode(),
        student_code_bidx=uuid.uuid4().bytes,
        password_hash="no-es-un-hash",
        role=UserRole.student,
        status=UserStatus.active,
        privacy_consent_at=datetime.now(UTC),
    )


@pytest.fixture
async def datos(sesiones: async_sessionmaker) -> Datos:
    """Una sala, dos equipos activos y dos estudiantes."""
    async with sesiones() as db:
        lab = Lab(name="Sala de pruebas")
        db.add(lab)
        await db.flush()
        pc01 = Machine(code="LAB-TEST-PC01", lab_id=lab.id, status=MachineStatus.active)
        pc02 = Machine(code="LAB-TEST-PC02", lab_id=lab.id, status=MachineStatus.active)
        ana, beto = _estudiante(1), _estudiante(2)
        db.add_all([pc01, pc02, ana, beto])
        await db.commit()
    return Datos(lab=lab, pc01=pc01, pc02=pc02, ana=ana, beto=beto)
