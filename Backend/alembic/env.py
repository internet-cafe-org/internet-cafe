import asyncio
import sys
from pathlib import Path
from logging.config import fileConfig

# Agrega la carpeta /backend al path de Python para que encuentre 'app'
sys.path.append(str(Path(__file__).resolve().parent.parent))

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importaciones de la aplicación
from app.database import Base
from app.models import *  # noqa
from app.config import settings
from app.db_url import preparar_conexion

# Esto lee el archivo alembic.ini
config = context.config

# Las migraciones corren con el rol svc_migrator (OPS-02): DATABASE_URL_MIGRATOR.
# Si no está definida (desarrollo local con docker-compose) se usa DATABASE_URL.
# La URL se normaliza para asyncpg (sslmode / channel_binding de Neon).
_url_migraciones, _connect_args = preparar_conexion(
    settings.database_url_migrator or settings.database_url
)
# configparser interpreta '%' como interpolación: se escapa para contraseñas codificadas
config.set_main_option("sqlalchemy.url", _url_migraciones.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Asocia el Metadata para las migraciones automáticas
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# OPS-02: la tabla de control de Alembic hereda los privilegios por defecto de svc_app
# (SELECT, INSERT, UPDATE). La API no debe poder alterar el estado de las migraciones,
# así que se le quitan al terminar. Es un no-op cuando no existe el rol (desarrollo
# local con docker-compose) o la tabla no está en el esquema `app`.
_REVOCAR_ALEMBIC_VERSION_A_SVC_APP = text(
    """
    DO $$
    BEGIN
        IF to_regclass('app.alembic_version') IS NOT NULL
           AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_app') THEN
            REVOKE ALL ON TABLE app.alembic_version FROM svc_app;
        END IF;
    END
    $$
    """
)


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()
        connection.execute(_REVOCAR_ALEMBIC_VERSION_A_SVC_APP)


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
