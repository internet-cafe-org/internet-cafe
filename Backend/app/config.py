"""Módulo de configuración de variables de entorno."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Entorno de despliegue: dev | prod | test (OPS-02: un proyecto Neon por entorno)
    app_env: str = "dev"

    # Conexión de RUNTIME: rol svc_app (sin DDL, sin DELETE). Nunca el dueño de la base.
    database_url: str
    # Conexión de MIGRACIONES: rol svc_migrator. Solo la usa Alembic (CI / servicio
    # migrador); no debe existir en el servidor de la API (SRS §12.8).
    database_url_migrator: str | None = None
    secret_key: str

    app_name: str = "Internet Cafe API"
    frontend_base_url: str = "http://localhost:5173"

    # Pool de conexiones del rol de la API (SRS §12.8: pools pequeños)
    db_pool_size: int = 5
    db_pool_recycle_s: int = 300  # Neon suspende el cómputo tras 5 min sin uso

    # Latido y cierre por inactividad (SRS §8.9)
    heartbeat_interval_s: int = 60
    heartbeat_timeout_s: int = 180

    # Cryptographic keys and token settings (SEC-00)
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_issuer: str = "internet-cafe-api"
    jwt_audience: str = "web"
    jwt_access_token_expire_minutes: int = 10
    data_enc_keys: str | None = None
    blind_index_key: str | None = None

    # Base del campo `type` de los errores RFC 9457 (ver app/errors.py)
    errors_base_url: str = "https://errors.internet-cafe.example"
    # Sesion web: refresh token en cookie (SEC-03a)
    refresh_token_expire_days: int = 7
    cookie_secure: bool = True
    allowed_origin: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
