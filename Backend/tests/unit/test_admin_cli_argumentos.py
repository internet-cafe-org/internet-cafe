"""Argumentos, entorno y salida de la CLI de administración (BE-20), sin base de datos."""

import uuid

import pytest

from app.services import usuarios
from app.services.passwords import PasswordPolicyError
from tools import admin_cli

CORREO = "persona@test.invalid"  # ficticio
ID = uuid.UUID(int=7)


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entorno mínimo válido: clave del índice ciego y contraseña ficticias."""
    monkeypatch.setenv("BLIND_INDEX_KEY", "1" * 64)
    monkeypatch.setenv("ADMIN_PASSWORD", "contrasena-larga")
    monkeypatch.delenv("ADMIN_CLI_EMAIL", raising=False)


def _simular(monkeypatch: pytest.MonkeyPatch, resultado=None, error: Exception | None = None):
    """Reemplaza la transacción real y guarda con qué se llamó."""
    llamadas: list[tuple] = []

    async def falsa(operacion, **kwargs):
        llamadas.append((operacion, kwargs))
        if error is not None:
            raise error
        return resultado

    monkeypatch.setattr(admin_cli, "_en_transaccion", falsa)
    return llamadas


def test_create_admin_imprime_solo_el_id(entorno, monkeypatch, capsys) -> None:
    llamadas = _simular(monkeypatch, resultado=type("Admin", (), {"id": ID})())

    codigo = admin_cli.main(["create-admin", "--email", CORREO, "--nombre", "Admin Prueba"])

    salida = capsys.readouterr()
    assert codigo == admin_cli.SALIDA_OK
    assert llamadas == [
        (
            usuarios.crear_admin,
            {"email": CORREO, "nombre": "Admin Prueba", "password": "contrasena-larga"},
        )
    ]
    assert str(ID) in salida.out
    assert CORREO not in salida.out + salida.err
    assert "contrasena-larga" not in salida.out + salida.err


def test_block_user_toma_el_correo_del_entorno(entorno, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ADMIN_CLI_EMAIL", CORREO)
    llamadas = _simular(
        monkeypatch, resultado=usuarios.ResultadoBloqueo(ID, False, 2, uuid.UUID(int=9))
    )

    codigo = admin_cli.main(["block-user"])

    salida = capsys.readouterr().out
    assert codigo == admin_cli.SALIDA_OK
    assert llamadas == [(usuarios.bloquear_usuario, {"email": CORREO})]
    assert "2 sesiones web revocadas" in salida
    assert CORREO not in salida


def test_block_user_sin_acceso_activo(entorno, monkeypatch, capsys) -> None:
    _simular(monkeypatch, resultado=usuarios.ResultadoBloqueo(ID, True, 0, None))

    assert admin_cli.main(["block-user", "--email", CORREO]) == admin_cli.SALIDA_OK
    assert "ya estaba bloqueada" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        usuarios.UsuarioNoEncontrado("No existe una cuenta con ese correo."),
        usuarios.UsuarioYaExiste("Ya existe una cuenta con ese correo."),
        PasswordPolicyError("La contraseña debe tener entre 10 y 128 caracteres."),
    ],
)
def test_errores_de_datos_salen_con_1(entorno, monkeypatch, capsys, error) -> None:
    _simular(monkeypatch, error=error)

    codigo = admin_cli.main(["create-admin", "--email", CORREO, "--nombre", "Admin"])

    assert codigo == admin_cli.SALIDA_DATOS
    assert str(error) in capsys.readouterr().err


@pytest.mark.parametrize(
    ("quitar", "argv"),
    [
        ("ADMIN_PASSWORD", ["create-admin", "--email", CORREO, "--nombre", "Admin"]),
        ("BLIND_INDEX_KEY", ["block-user", "--email", CORREO]),
        (None, ["block-user"]),  # sin --email ni ADMIN_CLI_EMAIL
    ],
)
def test_falta_configuracion_sale_con_2(entorno, monkeypatch, quitar, argv) -> None:
    if quitar:
        monkeypatch.delenv(quitar)
    llamadas = _simular(monkeypatch)

    assert admin_cli.main(argv) == admin_cli.SALIDA_CONFIGURACION
    assert llamadas == []


def test_la_contrasena_no_se_acepta_por_argumento(entorno) -> None:
    with pytest.raises(SystemExit):
        admin_cli.main(["create-admin", "--email", CORREO, "--nombre", "A", "--password", "x"])
