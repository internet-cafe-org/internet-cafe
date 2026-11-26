"""Módulo de configuración de variables de entorno."""

from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la API leída de variables de entorno o de ``.env``."""

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
    # Tarea periódica de inactividad (BE-09b): cada cuántos segundos revisa y si corre.
    inactividad_intervalo_s: int = 30
    tarea_inactividad_activa: bool = True

    # Autenticación del equipo (SEC-07, HU-19): token | dual | signature.
    # dual acepta la credencial provisional y, si llega, exige que la firma sea válida.
    machine_auth_mode: Literal["token", "dual", "signature"] = "dual"
    # Base pública con la que se arma @target-uri (no la URL interna de Render).
    public_api_base_url: str | None = None
    firma_tolerancia_s: int = 30
    # TRANSITORIO (solo dev): mientras el escritorio no envíe X-Machine-Key ni firma,
    # /machine/challenges y /wait aceptan solo X-Machine-Code. Con APP_ENV=prod se
    # ignora. Se apaga cuando Desktop se actualice (OPS-16) y se borra con SEC-14.
    retos_aceptan_solo_codigo: bool = False
    firma_ventana_nonce_s: int = 60

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
    # Orígenes extra permitidos en /auth/refresh y /auth/logout, separados por comas.
    # FRONTEND_BASE_URL siempre se permite (SEC-03b).
    allowed_origin: str | None = None
    # Solo con APP_ENV=dev: expresión regular de los previews de Vercel que también
    # se aceptan (p. ej. ^https://internet-cafe-[a-z0-9-]+\.vercel\.app$).
    origen_preview_regex: str | None = None
    # Gracia del refresh (SEC-03b): segundos en que el token recién rotado se acepta
    # otra vez, para que dos pestañas que renuevan a la vez no se cierren la sesión.
    refresh_gracia_s: int = 10

    # Registro (SEC-02). En el MVP las cuentas quedan activas sin OTP (backlog §4).
    require_email_verification: bool = False
    # Dominios de correo admitidos en el registro, separados por comas
    # (p. ej. "universidad.edu.co"). Vacío: se admite cualquier dominio (PEND-06).
    allowed_email_domains: str = ""

    # Correo transaccional (ST-BE-01).
    resend_api_key: SecretStr | None = None
    email_from: str = ""

    # Bloqueo de cuenta (SEC-09): tras N contraseñas fallidas, M minutos de bloqueo.
    login_max_intentos: int = 5
    login_bloqueo_minutos: int = 15

    # Rate limit (SEC-09, SRS §12.2): peticiones por minuto en /auth/*, /scan/claim
    # y /machine/enroll. Saltos de proxy confiables en X-Forwarded-For: la web pasa
    # por Vercel y Render (2); el escritorio va directo a Render (1).
    rate_limit_enabled: bool = True
    rate_limit_por_cuenta: int = 10
    rate_limit_por_ip: int = 10
    rate_limit_saltos_web: int = 2
    rate_limit_saltos_equipo: int = 1

    # Endurecimiento de la API (BE-21, SRS §12.9).
    # Hosts que la API acepta en la cabecera Host, separados por comas
    # (p. ej. "internet-cafe-tq03.onrender.com").
    # Vacío: no se restringe (desarrollo local, pruebas y CI).
    allowed_hosts: str = ""
    # Tamaño máximo del cuerpo de una petición, en bytes; si se supera, responde 413.
    max_body_bytes: int = 65536

    # Exportación CSV (ST-BE-03): zona horaria con la que se muestran las fechas.
    # Ej: "America/Bogota", "UTC", "Europe/Madrid".
    csv_timezone: str = "America/Bogota"

    @property
    def dominios_correo_permitidos(self) -> frozenset[str]:
        """Devuelve los dominios de ``ALLOWED_EMAIL_DOMAINS`` normalizados.

        Returns:
            Conjunto de dominios en minúsculas, sin espacios ni ``@``; vacío si
            no se configuró ninguno.
        """
        return frozenset(
            d.strip().lower().lstrip("@")
            for d in self.allowed_email_domains.split(",")
            if d.strip()
        )

    @property
    def hosts_permitidos(self) -> list[str]:
        """Devuelve los hosts de ``ALLOWED_HOSTS`` normalizados.

        Returns:
            Lista de hosts en minúsculas y sin espacios; vacía si no se configuró
            ninguno (en ese caso no se restringe la cabecera Host).
        """
        return [h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()]

    @model_validator(mode="after")
    def _validar_timezone(self) -> "Settings":
        """Valida que ``CSV_TIMEZONE`` sea una zona horaria reconocida.

        Returns:
            La propia configuración, sin cambios.

        Raises:
            ValueError: Si ``CSV_TIMEZONE`` no es una zona horaria válida.
        """
        try:
            ZoneInfo(self.csv_timezone)
        except Exception as exc:
            raise ValueError(f"CSV_TIMEZONE inválida: {self.csv_timezone}") from exc
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
