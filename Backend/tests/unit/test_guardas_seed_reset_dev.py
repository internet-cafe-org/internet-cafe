"""Guardas de la semilla y del reset de dev (QA-02a, OPS-11): sin red ni base."""

import pytest

from tools import reset_dev, seed_dev


def test_nombres_de_salas_y_equipos_son_estables() -> None:
    assert seed_dev.nombre_sala(1) == "Sala Dev 1"
    assert seed_dev.codigo_equipo(1, 3) == "DEV-S1-PC03"
    assert len(seed_dev.codigo_equipo(9, 99)) <= 40  # machines.code es String(40)


def test_codigos_de_enrolamiento_son_distintos_y_largos() -> None:
    codigos = {seed_dev.generar_codigo_enrolamiento() for _ in range(100)}
    assert len(codigos) == 100
    assert all(len(c) >= 22 for c in codigos)  # 16 bytes en base64url


@pytest.mark.parametrize("entorno", ["prod", "test", ""])
def test_semilla_se_niega_fuera_de_dev(entorno: str, monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", entorno)
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "contrasena-de-prueba")
    assert seed_dev.main([]) == 2
    assert "APP_ENV=dev" in capsys.readouterr().err


def test_semilla_exige_la_contrasena_y_no_la_imprime(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)
    assert seed_dev.main([]) == 2
    assert "SEED_ADMIN_PASSWORD" in capsys.readouterr().err


def test_codigos_sin_archivo_de_salida_se_rechazan(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "contrasena-de-prueba")
    assert seed_dev.main(["--codigos", "2"]) == 2
    assert "--salida-codigos" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("entorno", "confirmacion"), [("prod", "dev"), ("dev", "prod"), ("dev", "si"), ("", "dev")]
)
def test_reset_exige_dev_y_confirmacion(entorno: str, confirmacion: str, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", entorno)
    monkeypatch.setenv("DATABASE_URL_MIGRATOR", "postgresql://localhost/no_existe")
    assert reset_dev.main(["--confirmar", confirmacion]) == 2


def test_reset_exige_la_url_del_migrador(monkeypatch, capsys) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("DATABASE_URL_MIGRATOR", raising=False)
    assert reset_dev.main(["--confirmar", "dev"]) == 2
    assert "DATABASE_URL_MIGRATOR" in capsys.readouterr().err
