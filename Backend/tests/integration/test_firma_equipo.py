"""QA-09: pruebas de la firma por petición del equipo (SEC-07a y SEC-07b, HU-19).

Cubren alteración del cuerpo y de la URL, repetición, desfase de reloj, equipo
no activo y que un token responde 401 (SEC-14). Además, el
verificador se contrasta con los vectores compartidos de SEC-08, que son los
mismos que debe producir el firmador Java del escritorio.
"""

import base64
import hashlib
import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import obtener_base_datos
from app.main import app
from app.models import Machine, MachineStatus
from app.security import firma
from app.services.enrolamiento import huella_jwk
from tests.firmador import Firmador

BASE = "http://test"
VECTORES = Path(__file__).resolve().parents[3] / "contracts" / "test-vectors" / "vectores.json"


@pytest.fixture(autouse=True)
def nonces_limpios():
    """Cada prueba empieza sin nonces vistos."""
    firma.nonces.reiniciar()
    yield
    firma.nonces.reiniciar()


@pytest.fixture
def firmador() -> Firmador:
    """Par de claves del equipo de prueba."""
    return Firmador()


@pytest.fixture
async def equipo(sesiones, datos, firmador) -> Machine:
    """``pc01`` enrolado con la clave del firmador."""
    async with sesiones() as db:
        machine = await db.get(Machine, datos.pc01.id)
        machine.public_key_jwk = firmador.jwk
        machine.key_thumbprint = firmador.keyid
        await db.commit()
    return machine


@pytest.fixture
async def cliente(sesiones, monkeypatch):
    """Cliente HTTP con la base de pruebas y ``PUBLIC_API_BASE_URL`` sin fijar."""
    monkeypatch.setattr(settings, "public_api_base_url", None)

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c
    app.dependency_overrides.clear()


LATIDO = "/api/v1/machine/heartbeat"
CUERPO = b'{"session_id":null}'


async def _latido(cliente, cabeceras: dict, cuerpo: bytes = CUERPO, ruta: str = LATIDO):
    return await cliente.post(ruta, content=cuerpo, headers={"Content-Type": "application/json", **cabeceras})


# ---------------------------------------------------------------- camino feliz


async def test_latido_firmado_se_acepta(cliente, equipo, firmador):
    """Un latido bien firmado responde 200."""
    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == 200
    assert r.json()["session_status"] == "none"


async def test_get_firmado_sin_cuerpo_se_acepta(cliente, equipo, firmador):
    """Un GET sin cuerpo se firma sin ``content-digest``."""
    ruta = "/api/v1/machine/sessions/current"

    r = await cliente.get(ruta, headers=firmador.cabeceras("GET", BASE + ruta))

    assert r.status_code == 204


async def test_uri_con_public_api_base_url(cliente, equipo, firmador, monkeypatch):
    """La URI firmada es la pública, no la interna detrás del proxy."""
    monkeypatch.setattr(settings, "public_api_base_url", "https://api.internet-cafe.example/")

    publica = await _latido(cliente, firmador.cabeceras("POST", "https://api.internet-cafe.example" + LATIDO, CUERPO))
    interna = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert publica.status_code == 200
    assert interna.status_code == 401


# ---------------------------------------------------------------- alteraciones


async def test_cuerpo_alterado(cliente, equipo, firmador):
    """Cambiar el cuerpo después de firmar se rechaza."""
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO)

    r = await _latido(cliente, cab, cuerpo=b'{"session_id":"00000000-0000-0000-0000-000000000000"}')

    assert r.status_code == 401
    assert r.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_digest_recalculado_por_un_atacante(cliente, equipo, firmador):
    """Aunque el atacante recalcule Content-Digest, la firma ya no coincide."""
    otro = b'{"session_id":"00000000-0000-0000-0000-000000000000"}'
    cab = {**firmador.cabeceras("POST", BASE + LATIDO, CUERPO), "Content-Digest": firma.content_digest(otro)}

    r = await _latido(cliente, cab, cuerpo=otro)

    assert r.status_code == 401


async def test_url_alterada(cliente, equipo, firmador):
    """Una firma hecha para otra ruta no sirve."""
    cab = firmador.cabeceras("POST", BASE + "/api/v1/machine/sessions/current/end", CUERPO)

    r = await _latido(cliente, cab)

    assert r.status_code == 401


async def test_metodo_alterado(cliente, equipo, firmador):
    """Una firma de GET no sirve para un POST."""
    r = await _latido(cliente, firmador.cabeceras("GET", BASE + LATIDO), cuerpo=b"")

    assert r.status_code == 401


async def test_repeticion(cliente, equipo, firmador):
    """La misma petición firmada dos veces: la segunda se rechaza."""
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO)

    primera = await _latido(cliente, cab)
    segunda = await _latido(cliente, cab)

    assert primera.status_code == 200
    assert segunda.status_code == 401
    assert segunda.json()["code"] == "MACHINE_SIGNATURE_INVALID"


@pytest.mark.parametrize("desfase", [-31, 31])
async def test_reloj_desfasado(cliente, equipo, firmador, desfase):
    """Fuera de ±30 s responde ``MACHINE_CLOCK_SKEW`` (el equipo corrige con ``Date``)."""
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO, created=int(time.time()) + desfase)

    r = await _latido(cliente, cab)

    assert r.status_code == 401
    assert r.json()["code"] == "MACHINE_CLOCK_SKEW"


async def test_algoritmo_no_permitido(cliente, equipo, firmador):
    """Solo se acepta ``ecdsa-p256-sha256``."""
    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO, alg="hmac-sha256"))

    assert r.status_code == 401


async def test_clave_desconocida(cliente, equipo):
    """Una firma válida de una clave que no está enrolada se rechaza."""
    intruso = Firmador()

    r = await _latido(cliente, intruso.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == 401


async def test_cuerpo_sin_content_digest_firmado(cliente, equipo, firmador):
    """Si hay cuerpo, la firma debe cubrir ``content-digest``."""
    cab = firmador.cabeceras("POST", BASE + LATIDO)  # firmada como si no hubiera cuerpo

    r = await _latido(cliente, cab)

    assert r.status_code == 401


# ---------------------------------------------------------------- estado del equipo


@pytest.mark.parametrize(
    ("estado", "status", "code"),
    [(MachineStatus.disabled, 403, "MACHINE_DISABLED"),
     (MachineStatus.pending_enrollment, 401, "MACHINE_SIGNATURE_INVALID")],
)
async def test_equipo_no_activo(cliente, sesiones, equipo, firmador, estado, status, code):
    """Solo los equipos activos pueden firmar."""
    async with sesiones() as db:
        (await db.get(Machine, equipo.id)).status = estado
        await db.commit()

    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == status
    assert r.json()["code"] == code


# ---------------------------------------------------------------- credencial retirada (SEC-14)


TOKEN = {"X-Machine-Code": "LAB-TEST-PC01", "X-Machine-Key": "token-ficticio"}


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("POST", "/api/v1/machine/challenges"),
        ("GET", "/api/v1/machine/challenges/wait"),
        ("POST", LATIDO),
        ("GET", "/api/v1/machine/sessions/current"),
        ("POST", "/api/v1/machine/sessions/current/end"),
    ],
)
@pytest.mark.parametrize(
    "cabeceras",
    [TOKEN, {"X-Machine-Code": "LAB-TEST-PC01"}, {"Authorization": "Bearer token-ficticio"}, {}],
    ids=["token", "solo-codigo", "bearer", "sin-nada"],
)
async def test_sin_firma_responde_401(cliente, equipo, metodo, ruta, cabeceras):
    """Un token (o solo el código) responde 401 en todas las rutas del equipo."""
    r = await cliente.request(metodo, ruta, headers=cabeceras)

    assert r.status_code == 401
    assert r.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_un_token_no_salva_una_firma_invalida(cliente, equipo, firmador):
    """Con una firma inválida, enviar además el token no cambia el 401."""
    cab = {**TOKEN, **firmador.cabeceras("POST", BASE + "/otra/ruta", CUERPO)}

    r = await _latido(cliente, cab)

    assert r.status_code == 401


async def test_las_variables_viejas_no_reactivan_el_token(cliente, equipo, monkeypatch):
    """``MACHINE_AUTH_MODE`` y ``RETOS_ACEPTAN_SOLO_CODIGO`` ya no existen en la configuración."""
    monkeypatch.setenv("MACHINE_AUTH_MODE", "token")
    monkeypatch.setenv("RETOS_ACEPTAN_SOLO_CODIGO", "true")

    nueva = type(settings)()

    assert not hasattr(nueva, "machine_auth_mode")
    assert not hasattr(nueva, "retos_aceptan_solo_codigo")


# ---------------------------------------------------------------- vectores de SEC-08


def _casos():
    if not VECTORES.exists():
        return []
    return json.loads(VECTORES.read_text(encoding="utf-8"))["casos"]


@pytest.mark.skipif(not VECTORES.exists(), reason="faltan los vectores de SEC-08 (contracts/test-vectors)")
@pytest.mark.parametrize("caso", _casos(), ids=lambda c: c["nombre"])
def test_vectores_de_sec_08(caso):
    """El verificador reconstruye la misma base y acepta la firma de referencia."""
    datos = json.loads(VECTORES.read_text(encoding="utf-8"))
    jwk = datos["claves_solo_de_prueba"][caso["clave"]]["jwk_publica"]
    pet, esp = caso["peticion"], caso["esperado"]
    cuerpo = pet["cuerpo_utf8"].encode("utf-8") if pet["cuerpo_utf8"] is not None else None

    entrada = firma.leer_entrada(esp["signature_input"])
    digest = firma.content_digest(cuerpo) if cuerpo else None
    base = firma.base_de_firma(entrada, pet["metodo"], pet["base_publica"] + pet["ruta"], digest)

    assert list(entrada.componentes) == esp["componentes"]
    assert digest == esp["content_digest"]
    assert entrada.keyid == esp["keyid"] == huella_jwk(jwk)
    assert base == esp["base_de_firma"]
    assert firma.verificar_r_s(jwk, base, base64.b64decode(caso["firma_de_ejemplo"]))
    assert not firma.verificar_r_s(jwk, base + " ", base64.b64decode(caso["firma_de_ejemplo"]))


def test_nonce_se_libera_despues_de_la_ventana():
    """Un nonce visto vuelve a ser válido pasados 60 s."""
    memoria = firma._NoncesVistos()

    assert memoria.registrar("k", "n", ahora=0.0)
    assert not memoria.registrar("k", "n", ahora=59.0)
    assert memoria.registrar("k", "n", ahora=61.0)


def test_digest_de_referencia_rfc_9530():
    """El ejemplo del RFC 9530."""
    assert firma.content_digest(b'{"hello": "world"}') == "sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:"
    assert hashlib.sha256(b"").hexdigest()  # sanidad del entorno
