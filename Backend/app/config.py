
"""Módulo de configuración de variables de entorno."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    app_name: str = "Internet Cafe API"
    frontend_base_url: str = "http://localhost:5173"
    # Cryptographic keys and token settings (SEC-00)
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_issuer: str = "internet-cafe-api"
    jwt_audience: str = "web"
    jwt_access_token_expire_minutes: int = 10
    data_enc_keys: str | None = None
    blind_index_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
