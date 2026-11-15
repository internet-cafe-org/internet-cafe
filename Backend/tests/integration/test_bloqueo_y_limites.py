"""Pruebas de SEC-09: bloqueo tras 5 intentos fallidos y rate limit por cuenta e IP."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.config import settings
from app.models import AuditLog, User
from app.security import limites
from app.services import refresh_tokens
from tests.integration.test_auth_registro_login import (  # noqa: F401  (fixtures)
    CONTRASENA,
    _registro,
    claves,
    cliente,
)

RUTA = "/api/v1/auth"
CORREO = "estudiante.prueba@test.invalid"


async def _login(cliente, password: str = CONTRASENA, correo: str = CORREO, **kwargs):
    """Hace un login con el correo de prueba.

    Args:
        cliente: Cliente HTTP.
        password: Contraseña que se envía.
        correo: Correo que se envía.
        **kwargs: Argumentos extra para ``post`` (p. ej. cabeceras).

    Returns:
        La respuesta HTTP.
    """
    return await cliente.post(f"{RUTA}/login", json={"email": correo, "password": password}, **kwargs)


# ---------------------------------------------------------------- bloqueo de cuenta


async def test_cinco_fallos_bloquean_la_cuenta_15_minutos(cliente, sesiones):
    """El 5.º fallo bloquea; luego ni la contraseña correcta entra (423)."""
    await cliente.post(f"{RUTA}/register", json=_registro())

    fallos = [await _login(cliente, "contraseña equivocada") for _ in range(5)]
    bloqueado = await _login(cliente)

    assert [r.status_code for r in fallos] == [401] * 5
    assert bloqueado.status_code == 423
    assert bloqueado.json()["code"] == "AUTH_ACCOUNT_LOCKED"
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        acciones = (await db.scalars(select(AuditLog.action))).all()
    restante = usuario.locked_until - datetime.now(UTC)
    assert timedelta(minutes=14) < restante <= timedelta(minutes=15)
    assert "auth.lockout" in acciones


async def test_al_vencer_el_bloqueo_se_puede_entrar(cliente, sesiones):
    """Cuando ``locked_until`` ya pasó, la contraseña correcta entra y limpia el contador."""
    await cliente.post(f"{RUTA}/register", json=_registro())
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        usuario.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        usuario.failed_login_count = 3
        await db.commit()

    resp = await _login(cliente)

    assert resp.status_code == 200
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
    assert usuario.locked_until is None
    assert usuario.failed_login_count == 0


async def test_un_login_correcto_reinicia_el_contador(cliente, sesiones):
    """Cuatro fallos, un acierto y cuatro fallos más no bloquean."""
    await cliente.post(f"{RUTA}/register", json=_registro())

    for _ in range(4):
        await _login(cliente, "contraseña equivocada")
    assert (await _login(cliente)).status_code == 200
    for _ in range(4):
        await _login(cliente, "contraseña equivocada")

    assert (await _login(cliente)).status_code == 200


# ---------------------------------------------------------------- rate limit


async def test_limite_por_cuenta(cliente, monkeypatch):
    """La petición 11 de la misma cuenta en un minuto recibe 429 con Retry-After."""
    monkeypatch.setattr(settings, "rate_limit_por_ip", 1000)

    respuestas = [await _login(cliente, correo="nadie@test.invalid") for _ in range(11)]

    assert [r.status_code for r in respuestas[:10]] == [401] * 10
    assert respuestas[10].status_code == 429
    assert respuestas[10].json()["code"] == "RATE_LIMITED"
    assert int(respuestas[10].headers["retry-after"]) >= 1


async def test_limite_por_ip_con_saltos_confiables(cliente, monkeypatch):
    """Por IP cuenta la entrada confiable de X-Forwarded-For, no lo que escriba el cliente."""
    monkeypatch.setattr(settings, "rate_limit_por_ip", 3)

    def cabecera(ip_real: str, falsa: str) -> dict[str, str]:
        # El cliente escribe una IP falsa a la izquierda; Vercel agrega la real; Render la de Vercel.
        return {"X-Forwarded-For": f"{falsa}, {ip_real}, 10.0.0.1"}

    misma_ip = [
        await _login(cliente, correo=f"c{i}@test.invalid", headers=cabecera("203.0.113.7", f"1.1.1.{i}"))
        for i in range(4)
    ]
    otra_ip = await _login(cliente, correo="c9@test.invalid", headers=cabecera("198.51.100.2", "1.1.1.1"))

    assert [r.status_code for r in misma_ip] == [401, 401, 401, 429]
    assert otra_ip.status_code == 401


async def test_el_refresh_no_cuenta_para_el_limite_por_ip(cliente, sesiones, datos, monkeypatch):
    """Muchas renovaciones desde la misma IP no se bloquean entre sí."""
    monkeypatch.setattr(settings, "rate_limit_por_ip", 2)
    tokens = []
    async with sesiones() as db:
        for _ in range(5):
            tokens.append(await refresh_tokens.emitir(db, datos.ana.id, "pytest"))
        await db.commit()

    respuestas = []
    for token in tokens:
        cliente.cookies.clear()
        respuestas.append(
            await cliente.post(f"{RUTA}/refresh", headers={"Cookie": f"__Secure-rt={token}"})
        )

    assert [r.status_code for r in respuestas] == [200] * 5


async def test_rate_limit_se_puede_apagar(cliente, monkeypatch):
    """Con ``RATE_LIMIT_ENABLED=false`` no hay 429."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    respuestas = [await _login(cliente, correo="nadie@test.invalid") for _ in range(12)]

    assert all(r.status_code == 401 for r in respuestas)


# ---------------------------------------------------------------- unidades


def test_la_ventana_se_libera_despues_de_60_s():
    """Pasados 60 s desde la petición más vieja, se vuelve a permitir."""
    limitador = limites.LimitadorVentana()

    assert [limitador.registrar("k", 2, ahora=t) for t in (0.0, 1.0)] == [0, 0]
    assert limitador.registrar("k", 2, ahora=30.0) == 30
    assert limitador.registrar("k", 2, ahora=60.5) == 0


def _peticion(xff: str | None, ip_socket: str = "192.0.2.10") -> Request:
    """Arma una petición ASGI mínima para probar la IP del cliente.

    Args:
        xff: Valor de ``X-Forwarded-For`` o ``None``.
        ip_socket: IP del socket.

    Returns:
        La petición.
    """
    cabeceras = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": cabeceras, "client": (ip_socket, 1234)})


@pytest.mark.parametrize(
    ("xff", "origen", "esperada"),
    [
        ("6.6.6.6, 203.0.113.7, 10.0.0.1", limites.Origen.WEB, "203.0.113.7"),
        ("6.6.6.6, 203.0.113.7", limites.Origen.EQUIPO, "203.0.113.7"),
        ("203.0.113.7", limites.Origen.WEB, "192.0.2.10"),
        (None, limites.Origen.EQUIPO, "192.0.2.10"),
    ],
    ids=["web-2-saltos", "equipo-1-salto", "faltan-saltos", "sin-cabecera"],
)
def test_ip_del_cliente(xff, origen, esperada):
    """Solo se confía en los saltos configurados; si faltan, se usa la IP del socket."""
    assert limites.ip_del_cliente(_peticion(xff), origen) == esperada
