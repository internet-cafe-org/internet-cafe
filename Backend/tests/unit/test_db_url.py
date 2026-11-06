"""Normalización de URLs de Neon para asyncpg (OPS-02)."""

import pytest

from app.db_url import preparar_conexion

NEON = (
    "postgresql://svc_app:clave-ficticia@ep-ejemplo-123.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_url_de_neon_se_adapta_a_asyncpg() -> None:
    url, args = preparar_conexion(NEON)
    assert url == "postgresql+asyncpg://svc_app:clave-ficticia@ep-ejemplo-123.us-east-2.aws.neon.tech/neondb"
    assert args == {"ssl": "require"}


def test_se_quitan_sslmode_y_channel_binding_de_la_url() -> None:
    url, _ = preparar_conexion(NEON)
    assert "sslmode" not in url
    assert "channel_binding" not in url


def test_url_local_con_driver_no_cambia_y_no_pide_ssl() -> None:
    local = "postgresql+asyncpg://postgres:password123@db:5432/internet_cafe"
    assert preparar_conexion(local) == (local, {})


def test_esquema_postgres_corto_tambien_se_convierte() -> None:
    url, _ = preparar_conexion("postgres://u:p@h/db")
    assert url.startswith("postgresql+asyncpg://")


def test_otros_parametros_se_conservan() -> None:
    url, args = preparar_conexion("postgresql://u:p@h/db?application_name=api&sslmode=verify-full")
    assert "application_name=api" in url
    assert args == {"ssl": "verify-full"}


def test_contrasena_con_porcentaje_codificado_se_conserva() -> None:
    url, _ = preparar_conexion("postgresql://u:p%40ss@h/db?sslmode=require")
    assert "u:p%40ss@h" in url


def test_sslmode_desconocido_falla_sin_filtrar_la_url() -> None:
    with pytest.raises(ValueError) as error:
        preparar_conexion("postgresql://u:secreto-ficticio@h/db?sslmode=inventado")
    assert "secreto-ficticio" not in str(error.value)
