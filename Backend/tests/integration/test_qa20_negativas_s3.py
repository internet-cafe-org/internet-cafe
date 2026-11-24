"""QA-20: casos negativos de las historias Debería del Sprint 3 (HU-25, HU-33 y HU-34).

Completan lo que ya cubren ``test_cambio_password.py``, ``test_admin_export.py`` y
``test_sesiones.py``. Cada rechazo comprueba también que no cambió nada en la base.
Todos los datos son ficticios.
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.jwt import create_access_token
from app.models import (
    AuditLog,
    Machine,
    MachineStatus,
    SessionEndReason,
    User,
    UserStatus,
)
from app.routers import admin as router_admin
from app.services import pii, refresh_tokens
from app.services import sesiones as servicio_sesiones
from app.services.passwords import verify_password
from tests.integration.test_admin_export import (  # noqa: F401  (fixtures)
    _bearer_admin,
    _crear_sesion,
    admin_user,
    configurar_llave_blind_index,
)
from tests.integration.test_cambio_password import (  # noqa: F401  (fixtures)
    CLAVE_ACTUAL,
    CLAVE_NUEVA,
    _bearer,
    _con_clave,
    _hash_guardado,
    _revocado_en,
    claves,
    cliente,
)
from tests.integration.test_firma_equipo import Firmador
from tests.integration.test_sesiones import (  # noqa: F401  (fixtures)
    TIMEOUT,
    abrir_sesion,
    cerrar_inactivas,
    leer_sesion,
    reloj,
    seg,
)

PASSWORD = "/api/v1/me/password"
EXPORT = "/api/v1/admin/sessions/export"
CIERRE = "/api/v1/machine/sessions/current/end"
CAMBIO = {"current_password": CLAVE_ACTUAL, "new_password": CLAVE_NUEVA}


async def _auditorias(sesiones, accion: str) -> int:
    async with sesiones() as db:
        return await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == accion)
        )


def _token_vencido(claves, usuario, rol: str) -> dict[str, str]:
    token = create_access_token(
        subject=str(usuario.id), role=rol, private_key=claves, expires_delta=timedelta(minutes=-5)
    )
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- HU-25 · cambio de contraseña


async def _sigue_igual(sesiones, usuario) -> None:
    """La contraseña no cambió y no quedó auditoría de un cambio."""
    assert verify_password(CLAVE_ACTUAL, await _hash_guardado(sesiones, usuario))
    assert await _auditorias(sesiones, "auth.password_change") == 0


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"current_password": CLAVE_ACTUAL, "new_password": "n" * 9},
        {"current_password": CLAVE_ACTUAL, "new_password": "n" * 129},
        {"current_password": CLAVE_ACTUAL, "new_password": ""},
        {"current_password": "", "new_password": CLAVE_NUEVA},
        {"current_password": "a" * 129, "new_password": CLAVE_NUEVA},
        {"current_password": CLAVE_ACTUAL, "new_password": None},
        {"current_password": CLAVE_ACTUAL, "new_password": 1234567890},
        {"current_password": CLAVE_ACTUAL},
        {"new_password": CLAVE_NUEVA},
        {},
    ],
    ids=[
        "nueva-de-9",
        "nueva-de-129",
        "nueva-vacia",
        "actual-vacia",
        "actual-de-129",
        "nueva-nula",
        "nueva-numerica",
        "sin-nueva",
        "sin-actual",
        "sin-campos",
    ],
)
async def test_cambio_con_cuerpo_invalido(cliente, claves, datos, sesiones, cuerpo):
    """Fuera de la política (10 a 128) o incompleto → 422, sin repetir lo enviado."""
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(PASSWORD, json=cuerpo, headers=_bearer(claves, datos.ana))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert CLAVE_ACTUAL not in resp.text
    assert CLAVE_NUEVA not in resp.text
    await _sigue_igual(sesiones, datos.ana)


@pytest.mark.parametrize("largo", [10, 128])
async def test_cambio_acepta_los_limites_de_la_politica(cliente, claves, datos, sesiones, largo):
    """Los extremos 10 y 128 sí se aceptan: el rechazo empieza justo fuera de ellos."""
    await _con_clave(sesiones, datos.ana)
    nueva = "n" * largo

    resp = await cliente.patch(
        PASSWORD,
        json={"current_password": CLAVE_ACTUAL, "new_password": nueva},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 204
    assert verify_password(nueva, await _hash_guardado(sesiones, datos.ana))


async def test_cambio_con_la_actual_incorrecta_no_cierra_sesiones(cliente, claves, datos, sesiones):
    """Un intento fallido no revoca sesiones web ni deja auditoría de cambio."""
    await _con_clave(sesiones, datos.ana)
    async with sesiones() as db:
        refresco = await refresh_tokens.emitir(db, datos.ana.id)
        await db.commit()

    resp = await cliente.patch(
        PASSWORD,
        json={"current_password": "OtraClave-incorrecta", "new_password": CLAVE_NUEVA},
        headers=_bearer(claves, datos.ana),
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_CURRENT_PASSWORD_INVALID"
    assert await _revocado_en(sesiones, refresco) is None
    await _sigue_igual(sesiones, datos.ana)


async def test_cambio_no_toca_a_otro_estudiante(cliente, claves, datos, sesiones):
    """Cambiar la de Ana no cambia la contraseña ni las sesiones de Beto."""
    await _con_clave(sesiones, datos.ana)
    await _con_clave(sesiones, datos.beto)
    async with sesiones() as db:
        refresco_beto = await refresh_tokens.emitir(db, datos.beto.id)
        await db.commit()

    resp = await cliente.patch(PASSWORD, json=CAMBIO, headers=_bearer(claves, datos.ana))

    assert resp.status_code == 204
    assert verify_password(CLAVE_ACTUAL, await _hash_guardado(sesiones, datos.beto))
    assert await _revocado_en(sesiones, refresco_beto) is None


async def test_cambio_con_token_vencido(cliente, claves, datos, sesiones):
    """El token vencido tiene su propio código, distinto del de la contraseña."""
    await _con_clave(sesiones, datos.ana)

    resp = await cliente.patch(
        PASSWORD, json=CAMBIO, headers=_token_vencido(claves, datos.ana, "student")
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_TOKEN_EXPIRED"
    await _sigue_igual(sesiones, datos.ana)


async def test_cambio_con_cuenta_bloqueada(cliente, claves, datos, sesiones):
    """Una cuenta bloqueada no cambia su contraseña aunque su token siga vigente."""
    await _con_clave(sesiones, datos.ana)
    async with sesiones() as db:
        (await db.get(User, datos.ana.id)).status = UserStatus.blocked
        await db.commit()

    resp = await cliente.patch(PASSWORD, json=CAMBIO, headers=_bearer(claves, datos.ana))

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
    await _sigue_igual(sesiones, datos.ana)


async def test_cambio_de_un_usuario_que_no_existe(cliente, claves, datos):
    """Un token válido de una cuenta inexistente → 401."""
    token = create_access_token(subject=str(uuid.uuid4()), role="student", private_key=claves)

    resp = await cliente.patch(PASSWORD, json=CAMBIO, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_cambio_limita_los_intentos(cliente, claves, datos, sesiones, monkeypatch):
    """Superado el límite → 429, ni la contraseña correcta pasa; otra cuenta no se afecta."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_por_cuenta", 3)
    await _con_clave(sesiones, datos.ana)
    await _con_clave(sesiones, datos.beto)
    malo = {"current_password": "OtraClave-incorrecta", "new_password": CLAVE_NUEVA}

    fallos = [
        await cliente.patch(PASSWORD, json=malo, headers=_bearer(claves, datos.ana))
        for _ in range(3)
    ]
    limitado = await cliente.patch(PASSWORD, json=CAMBIO, headers=_bearer(claves, datos.ana))
    de_beto = await cliente.patch(PASSWORD, json=CAMBIO, headers=_bearer(claves, datos.beto))

    assert [r.status_code for r in fallos] == [401] * 3
    assert limitado.status_code == 429
    assert limitado.json()["code"] == "RATE_LIMITED"
    assert int(limitado.headers["retry-after"]) > 0
    assert verify_password(CLAVE_ACTUAL, await _hash_guardado(sesiones, datos.ana))
    assert de_beto.status_code == 204


# --------------------------------------------------------------- HU-33 · exportación CSV


def _filas(resp) -> list[list[str]]:
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))


async def test_exportar_sin_token(cliente, sesiones, datos):
    """Sin sesión no hay archivo ni auditoría."""
    resp = await cliente.get(EXPORT)

    assert resp.status_code == 401
    assert "text/csv" not in resp.headers["content-type"]
    assert await _auditorias(sesiones, "admin_export_csv") == 0


async def test_exportar_con_token_vencido(cliente, claves, sesiones, admin_user):
    """Un administrador con el token vencido tampoco exporta."""
    resp = await cliente.get(EXPORT, headers=_token_vencido(claves, admin_user, "admin"))

    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_TOKEN_EXPIRED"
    assert await _auditorias(sesiones, "admin_export_csv") == 0


async def test_exportar_como_estudiante_no_entrega_datos(cliente, claves, sesiones, datos):
    """Un estudiante recibe 403 sin datos de otros y sin auditoría de exportación."""
    await _crear_sesion(sesiones, datos.beto, datos.pc01, hace_min=10)

    resp = await cliente.get(EXPORT, headers=_bearer(claves, datos.ana))

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"
    assert "Estudiante Prueba 2" not in resp.text
    assert await _auditorias(sesiones, "admin_export_csv") == 0


@pytest.mark.parametrize(
    "filtro",
    [
        {"state": "cerrada"},
        {"lab_id": "no-es-uuid"},
        {"started_from": "ayer"},
        {"started_to": "2026-13-45"},
        {"machine_code": "X" * 41},
        {"student": "X" * 81},
    ],
    ids=["state", "lab_id", "started_from", "started_to", "machine_code", "student"],
)
async def test_exportar_con_filtro_invalido(cliente, claves, sesiones, admin_user, filtro):
    """Un filtro inválido se rechaza: no se ignora ni se exporta todo."""
    resp = await cliente.get(EXPORT, params=filtro, headers=_bearer_admin(claves, admin_user))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert await _auditorias(sesiones, "admin_export_csv") == 0


@pytest.mark.parametrize(
    "filtro",
    [
        {"machine_code": "NO-EXISTE"},
        {"lab_id": "00000000-0000-0000-0000-000000000000"},
        {"state": "active"},
        {"started_from": "2099-01-01T00:00:00Z"},
        {"started_from": "2026-11-20T00:00:00Z", "started_to": "2026-11-01T00:00:00Z"},
        {"student": "nadie@test.invalid"},
        {"student": "' OR 1=1 --"},
    ],
    ids=["equipo", "sala", "estado", "futuro", "rango-invertido", "estudiante", "inyeccion-sql"],
)
async def test_exportar_sin_resultados_da_solo_la_cabecera(
    cliente, claves, sesiones, datos, admin_user, filtro
):
    """Con filtros que no coinciden, el CSV trae solo los títulos y no otros accesos."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)

    resp = await cliente.get(EXPORT, params=filtro, headers=_bearer_admin(claves, admin_user))

    assert resp.status_code == 200
    assert len(_filas(resp)) == 1
    assert "x-export-truncated" not in resp.headers


async def test_exportar_filtra_por_equipo(cliente, claves, sesiones, datos, admin_user):
    """Un acceso fuera del filtro no se cuela en el archivo."""
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)
    await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=20)

    resp = await cliente.get(
        EXPORT, params={"machine_code": datos.pc01.code}, headers=_bearer_admin(claves, admin_user)
    )

    assert [f[2] for f in _filas(resp)[1:]] == [datos.pc01.code]


@pytest.mark.parametrize("inicio", ["=", "+", "-", "@", "\t", "\r"])
async def test_exportar_neutraliza_cada_inicio_de_formula(
    cliente, claves, sesiones, datos, admin_user, inicio
):
    """Ningún inicio que Excel interpreta como fórmula llega sin la comilla."""
    nombre = f"{inicio}HYPERLINK(1)"
    async with sesiones() as db:
        (await db.get(User, datos.ana.id)).full_name_ct = nombre.encode()
        await db.commit()
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)

    resp = await cliente.get(EXPORT, headers=_bearer_admin(claves, admin_user))

    # newline="": el lector conserva el retorno de carro dentro de la celda
    texto = resp.content.decode("utf-8-sig")
    filas = list(csv.reader(io.StringIO(texto, newline="")))
    assert filas[1][0] == f"'{nombre}"


async def test_exportar_no_revela_datos_personales(cliente, claves, sesiones, datos, admin_user):
    """Ni el archivo trae el código completo o el correo, ni la auditoría el filtro buscado."""
    correo, codigo = "estudiante1@test.invalid", "0000000001"
    async with sesiones() as db:
        (await db.get(User, datos.ana.id)).email_bidx = pii.indice_ciego(correo)
        await db.commit()
    await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10)

    resp = await cliente.get(
        EXPORT, params={"student": correo}, headers=_bearer_admin(claves, admin_user)
    )

    assert len(_filas(resp)) == 2
    assert codigo not in resp.text
    assert correo not in resp.text
    async with sesiones() as db:
        metadatos = await db.scalar(
            select(AuditLog.metadata_info).where(AuditLog.action == "admin_export_csv")
        )
    assert metadatos["filtros"]["has_student"] is True
    assert correo not in json.dumps(metadatos)


@pytest.mark.parametrize(("accesos", "truncado"), [(2, False), (3, True)])
async def test_exportar_avisa_si_se_corta(
    cliente, claves, sesiones, datos, admin_user, monkeypatch, accesos, truncado
):
    """Con más filas que el máximo se corta y se avisa; justo en el máximo, no."""
    monkeypatch.setattr(router_admin, "LIMITE_FILAS_CSV", 2)
    for n in range(accesos):
        await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=10 * (n + 1))

    resp = await cliente.get(EXPORT, headers=_bearer_admin(claves, admin_user))

    assert len(_filas(resp)) == 3
    assert resp.headers.get("x-export-truncated") == ("true" if truncado else None)


# --------------------------------------------------------------- HU-34 · cierre al apagar


@pytest.fixture
async def firmador(sesiones, datos, monkeypatch) -> Firmador:
    """``pc01`` enrolado: se autentica con firma, como el escritorio."""
    monkeypatch.setattr(settings, "public_api_base_url", None)
    nuevo = Firmador()
    async with sesiones() as db:
        machine = await db.get(Machine, datos.pc01.id)
        machine.public_key_jwk = nuevo.jwk
        machine.key_thumbprint = nuevo.keyid
        await db.commit()
    return nuevo


async def _apagar(cliente, firmador, cuerpo: dict | None = None, firmado: bytes | None = None):
    """Envía el cierre al apagar; ``firmado`` simula un cuerpo distinto del que se firmó."""
    crudo = json.dumps(cuerpo or {"reason": "machine_shutdown"}).encode()
    cabeceras = firmador.cabeceras("POST", f"https://testserver{CIERRE}", firmado or crudo)
    return await cliente.post(
        CIERRE, content=crudo, headers={"Content-Type": "application/json", **cabeceras}
    )


async def test_apagar_sin_firma_no_cierra(cliente, sesiones, datos, reloj, firmador):
    """Sin firma nadie puede cerrar el acceso de un equipo."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    resp = await cliente.post(CIERRE, json={"reason": "machine_shutdown"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


async def test_apagar_con_el_cuerpo_alterado_no_cierra(cliente, sesiones, datos, reloj, firmador):
    """Cambiar el motivo después de firmar invalida la petición."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    resp = await _apagar(cliente, firmador, firmado=b'{"reason":"user_logout_pc"}')

    assert resp.status_code == 401
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"reason": "heartbeat_timeout"},
        {"reason": "superseded"},
        {"reason": "user_logout_web"},
        {"reason": "apagado"},
        {"reason": None},
        {"reason": "machine_shutdown", "ended_at": "2020-01-01T00:00:00Z"},
    ],
    ids=["inactividad", "reemplazo", "web", "desconocido", "nulo", "hora-del-cliente"],
)
async def test_apagar_con_cuerpo_invalido_no_cierra(
    cliente, sesiones, datos, reloj, firmador, cuerpo
):
    """El equipo no elige motivos ajenos ni la hora del cierre."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)

    resp = await _apagar(cliente, firmador, cuerpo)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


async def test_apagar_un_equipo_deshabilitado(cliente, sesiones, datos, reloj, firmador):
    """Un equipo deshabilitado recibe 403; su acceso lo cubre el cierre por inactividad."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    async with sesiones() as db:
        (await db.get(Machine, datos.pc01.id)).status = MachineStatus.disabled
        await db.commit()

    resp = await _apagar(cliente, firmador)

    assert resp.status_code == 403
    assert resp.json()["code"] == "MACHINE_DISABLED"
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None


async def test_apagar_sin_sesion_no_audita(cliente, sesiones, datos, reloj, firmador):
    """Apagar un PC libre responde 404 y no deja un cierre en la auditoría."""
    resp = await _apagar(cliente, firmador)

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"
    assert await _auditorias(sesiones, "session_ended") == 0


async def test_apagar_no_cierra_la_sesion_de_otro_equipo(cliente, sesiones, datos, reloj, firmador):
    """La firma de pc01 no alcanza la sesión de pc02."""
    beto = await abrir_sesion(sesiones, datos.pc02, datos.beto, 0)

    resp = await _apagar(cliente, firmador)

    assert resp.status_code == 404
    assert (await leer_sesion(sesiones, beto.id)).ended_at is None


async def test_apagar_despues_de_un_cierre_forzado_no_lo_pisa(
    cliente, sesiones, datos, reloj, firmador
):
    """Si el administrador cerró antes, apagar no cambia el motivo ni la hora."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    async with sesiones() as db:
        await servicio_sesiones.cerrar_sesion_abierta(
            db, sesion.id, SessionEndReason.admin_forced, seg(50)
        )
        await db.commit()
    reloj.en(100)

    resp = await _apagar(cliente, firmador)

    assert resp.status_code == 404
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.ended_at == seg(50)
    assert guardada.end_reason == SessionEndReason.admin_forced


async def test_si_el_cierre_no_sale_lo_cubre_la_inactividad(
    cliente, sesiones, datos, reloj, firmador
):
    """El aviso no salió: cierra la inactividad, y un aviso tardío ya no lo cambia."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    ultimo = (await leer_sesion(sesiones, sesion.id)).last_heartbeat_at

    antes = await cerrar_inactivas(sesiones, ultimo + timedelta(seconds=TIMEOUT - 1))
    despues = await cerrar_inactivas(sesiones, ultimo + timedelta(seconds=TIMEOUT))
    reloj.en(TIMEOUT + 60)
    tardio = await _apagar(cliente, firmador)

    assert (antes, despues) == (0, 1)
    assert tardio.status_code == 404
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.end_reason == SessionEndReason.heartbeat_timeout
    assert guardada.ended_at == ultimo


async def test_un_cierre_al_apagar_no_lo_vuelve_a_cerrar_la_inactividad(
    cliente, sesiones, datos, reloj, firmador
):
    """Cerrada al apagar, la tarea de inactividad ya no la toca."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(100)

    resp = await _apagar(cliente, firmador)
    cerradas = await cerrar_inactivas(sesiones, seg(100 + TIMEOUT * 2))

    assert resp.status_code == 200
    assert cerradas == 0
    guardada = await leer_sesion(sesiones, sesion.id)
    assert guardada.end_reason == SessionEndReason.machine_shutdown
    assert guardada.ended_at == seg(100)


async def test_repetir_la_misma_peticion_de_apagado_se_rechaza(
    cliente, sesiones, datos, reloj, firmador
):
    """Capturar y reenviar el cierre no sirve: el nonce ya se usó."""
    await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    reloj.en(100)
    crudo = b'{"reason":"machine_shutdown"}'
    cabeceras = {
        "Content-Type": "application/json",
        **firmador.cabeceras("POST", f"https://testserver{CIERRE}", crudo),
    }

    primera = await cliente.post(CIERRE, content=crudo, headers=cabeceras)
    repetida = await cliente.post(CIERRE, content=crudo, headers=cabeceras)

    assert primera.status_code == 200
    assert repetida.status_code == 401
    assert repetida.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_apagar_con_el_reloj_desfasado(cliente, sesiones, datos, reloj, firmador):
    """Con el reloj fuera de tolerancia → ``MACHINE_CLOCK_SKEW`` y la sesión sigue abierta."""
    sesion = await abrir_sesion(sesiones, datos.pc01, datos.ana, 0)
    crudo = b'{"reason":"machine_shutdown"}'
    vieja = int(datetime.now(UTC).timestamp()) - settings.firma_tolerancia_s - 5
    cabeceras = firmador.cabeceras("POST", f"https://testserver{CIERRE}", crudo, created=vieja)

    resp = await cliente.post(
        CIERRE, content=crudo, headers={"Content-Type": "application/json", **cabeceras}
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_CLOCK_SKEW"
    assert (await leer_sesion(sesiones, sesion.id)).ended_at is None
