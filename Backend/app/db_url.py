"""Normaliza URLs de PostgreSQL (local y Neon) para SQLAlchemy + asyncpg (OPS-02).

Neon entrega URLs de libpq, por ejemplo:
    postgresql://svc_app:...@ep-xxx.neon.tech/neondb?sslmode=require&channel_binding=require
asyncpg no entiende `sslmode` ni `channel_binding` en la URL (falla con
"unexpected keyword argument"), así que se quitan de la URL y `sslmode` pasa a
`connect_args["ssl"]`, que asyncpg sí acepta con los mismos valores.

Los mensajes de error nunca incluyen la URL: lleva la contraseña.
"""

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Valores de sslmode que asyncpg acepta en su parámetro `ssl`
SSLMODES_VALIDOS = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


def preparar_conexion(url: str) -> tuple[str, dict[str, Any]]:
    """Devuelve (url para `create_async_engine`, `connect_args`).

    - `postgres://` y `postgresql://` pasan a `postgresql+asyncpg://`.
    - `sslmode=<modo>` se traslada a `connect_args={"ssl": "<modo>"}`.
    - `channel_binding` se descarta: asyncpg no lo expone y la integridad del canal la
      da TLS (SRS §12.7 pide sslmode=require).
    - El resto de parámetros de la consulta se conserva.
    """
    partes = urlsplit(url)
    esquema = partes.scheme
    if esquema in ("postgres", "postgresql"):
        esquema = "postgresql+asyncpg"

    sslmode: str | None = None
    resto: list[tuple[str, str]] = []
    for clave, valor in parse_qsl(partes.query, keep_blank_values=True):
        if clave == "sslmode":
            sslmode = valor
        elif clave == "channel_binding":
            continue
        else:
            resto.append((clave, valor))

    connect_args: dict[str, Any] = {}
    if sslmode is not None:
        if sslmode not in SSLMODES_VALIDOS:
            raise ValueError(f"sslmode no soportado: {sslmode!r}")
        connect_args["ssl"] = sslmode

    url_limpia = urlunsplit((esquema, partes.netloc, partes.path, urlencode(resto), partes.fragment))
    return url_limpia, connect_args
