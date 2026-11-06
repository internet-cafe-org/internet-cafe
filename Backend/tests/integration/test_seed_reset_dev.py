"""Semilla idempotente y reset de dev contra PostgreSQL real (QA-02a, OPS-11)."""

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.crypto import compute_blind_index, sha256_digest
from app.database import Base
from app.models import EnrollmentCode, Lab, Machine, User, UserRole, UserStatus
from app.services.passwords import verify_password
from tools.reset_dev import vaciar_esquema
from tools.seed_dev import sembrar

CLAVE_BIDX = "0" * 64  # ficticia, solo para la prueba
EMAIL = "admin@dev.invalid"


async def _sembrar(sesiones: async_sessionmaker, password: str, codigos: int = 0):
    async with sesiones() as db:
        resumen = await sembrar(
            db,
            admin_email=EMAIL,
            admin_password=password,
            blind_index_key=CLAVE_BIDX,
            salas=2,
            equipos_por_sala=2,
            codigos=codigos,
        )
        await db.commit()
    return resumen


async def _contar(sesiones: async_sessionmaker, modelo) -> int:
    async with sesiones() as db:
        return await db.scalar(select(func.count()).select_from(modelo))


async def test_semilla_crea_los_datos_de_dev(sesiones: async_sessionmaker) -> None:
    resumen = await _sembrar(sesiones, "contrasena-uno")

    assert resumen.admin_creado
    assert (resumen.salas_creadas, resumen.equipos_creados) == (2, 4)
    async with sesiones() as db:
        admin = await db.scalar(
            select(User).where(User.email_bidx == compute_blind_index(EMAIL, CLAVE_BIDX))
        )
    assert admin.role == UserRole.admin
    assert admin.status == UserStatus.active
    assert verify_password("contrasena-uno", admin.password_hash)


async def test_semilla_es_idempotente(sesiones: async_sessionmaker) -> None:
    await _sembrar(sesiones, "contrasena-uno")
    resumen = await _sembrar(sesiones, "contrasena-dos")

    assert not resumen.admin_creado
    assert (resumen.salas_creadas, resumen.equipos_creados) == (0, 0)
    assert await _contar(sesiones, User) == 1
    assert await _contar(sesiones, Lab) == 2
    assert await _contar(sesiones, Machine) == 4
    async with sesiones() as db:
        admin = await db.scalar(select(User))
    assert verify_password("contrasena-dos", admin.password_hash)


async def test_codigos_se_guardan_solo_como_hash(sesiones: async_sessionmaker) -> None:
    resumen = await _sembrar(sesiones, "contrasena-uno", codigos=3)

    assert len(resumen.codigos) == 3
    async with sesiones() as db:
        hashes = set((await db.scalars(select(EnrollmentCode.code_hash))).all())
    assert hashes == {sha256_digest(codigo) for _, codigo in resumen.codigos}


async def test_reset_vacia_el_esquema_app(motor: AsyncEngine, sesiones: async_sessionmaker) -> None:
    await _sembrar(sesiones, "contrasena-uno")
    async with motor.begin() as conn:
        await conn.execute(text("CREATE TYPE app.tipo_de_prueba AS ENUM ('a')"))

    async with motor.begin() as conn:
        tablas, tipos = await vaciar_esquema(conn)
        quedan = await conn.scalar(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'app'")
        )

    assert tablas == len(Base.metadata.sorted_tables)
    assert tipos >= 1
    assert quedan == 0
    # La fixture `motor` hace TRUNCATE al final: se recrean las tablas
    async with motor.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
