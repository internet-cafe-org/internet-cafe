"""QA-09: pruebas de la firma por petición del equipo (SEC-07a y SEC-07b, HU-19).

Cubren alteración del cuerpo y de la URL, repetición, desfase de reloj, equipo
no activo y los modos ``token``, ``dual`` y ``signature``. Además, el
verificador se contrasta con los vectores compartidos de SEC-08, que son los
mismos que debe producir el firmador Java del escritorio.
"""

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import obtener_base_datos
from app.main import app
from app.models import Machine, MachineStatus
from app.security import firma
from app.security.dependencies import hash_machine_credential
from app.services.enrolamiento import huella_jwk

BASE = "http://test"
VECTORES = Path(__file__).resolve().parents[3] / "contracts" / "test-vectors" / "vectores.json"


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


class Firmador:
    """Firma peticiones como el escritorio, con el perfil de SEC-08."""

    def __init__(self) -> None:
        """Genera un par P-256 y su JWK público."""
        self.clave = ec.generate_private_key(ec.SECP256R1())
        n = self.clave.public_key().public_numbers()
        self.jwk = {"kty": "EC", "crv": "P-256",
                    "x": _b64url(n.x.to_bytes(32, "big")), "y": _b64url(n.y.to_bytes(32, "big"))}
        self.keyid = huella_jwk(self.jwk)

    def cabeceras(self, metodo: str, uri: str, cuerpo: bytes = b"", *, created: int | None = None,
                  nonce: str | None = None, alg: str = firma.ALGORITMO) -> dict[str, str]:
        """Arma las cabeceras ``Signature-Input``, ``Signature`` y ``Content-Digest``.

        Args:
            metodo: Método HTTP.
            uri: ``@target-uri`` absoluta que se firma.
            cuerpo: Cuerpo de la petición.
            created: Momento de la firma (por defecto, ahora).
            nonce: Nonce (por defecto, uno aleatorio).
            alg: Algoritmo declarado.

        Returns:
            Las cabeceras de la petición firmada.
        """
        created = int(time.time()) if created is None else created
        nonce = nonce or secrets.token_urlsafe(12)
        componentes = ["@method", "@target-uri"] + (["content-digest"] if cuerpo else [])
        lista = " ".join(f'"{c}"' for c in componentes)
        params = f'({lista});created={created};keyid="{self.keyid}";alg="{alg}";nonce="{nonce}"'
        valores = {"@method": metodo, "@target-uri": uri, "content-digest": firma.content_digest(cuerpo)}
        base = "\n".join([f'"{c}": {valores[c]}' for c in componentes] + [f'"@signature-params": {params}'])
        r, s = decode_dss_signature(self.clave.sign(base.encode(), ec.ECDSA(hashes.SHA256())))
        cab = {"Signature-Input": f"sig1={params}",
               "Signature": f"sig1=:{base64.b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).decode()}:"}
        if cuerpo:
            cab["Content-Digest"] = firma.content_digest(cuerpo)
        return cab


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
    """``pc01`` enrolado con la clave del firmador y una credencial provisional."""
    async with sesiones() as db:
        machine = await db.get(Machine, datos.pc01.id)
        machine.public_key_jwk = firmador.jwk
        machine.key_thumbprint = firmador.keyid
        machine.credential_hash = hash_machine_credential("clave-pc01")
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


def _modo(monkeypatch, modo: str) -> None:
    monkeypatch.setattr(settings, "machine_auth_mode", modo)


LATIDO = "/api/v1/machine/heartbeat"
CUERPO = b'{"session_id":null}'


async def _latido(cliente, cabeceras: dict, cuerpo: bytes = CUERPO, ruta: str = LATIDO):
    return await cliente.post(ruta, content=cuerpo, headers={"Content-Type": "application/json", **cabeceras})


# ---------------------------------------------------------------- camino feliz


async def test_latido_firmado_se_acepta(cliente, equipo, firmador, monkeypatch):
    """En modo ``signature`` un latido bien firmado responde 200."""
    _modo(monkeypatch, "signature")

    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == 200
    assert r.json()["session_status"] == "none"


async def test_get_firmado_sin_cuerpo_se_acepta(cliente, equipo, firmador, monkeypatch):
    """Un GET sin cuerpo se firma sin ``content-digest``."""
    _modo(monkeypatch, "signature")
    ruta = "/api/v1/machine/sessions/current"

    r = await cliente.get(ruta, headers=firmador.cabeceras("GET", BASE + ruta))

    assert r.status_code == 204


async def test_uri_con_public_api_base_url(cliente, equipo, firmador, monkeypatch):
    """La URI firmada es la pública, no la interna detrás del proxy."""
    _modo(monkeypatch, "signature")
    monkeypatch.setattr(settings, "public_api_base_url", "https://api.internet-cafe.example/")

    publica = await _latido(cliente, firmador.cabeceras("POST", "https://api.internet-cafe.example" + LATIDO, CUERPO))
    interna = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert publica.status_code == 200
    assert interna.status_code == 401


# ---------------------------------------------------------------- alteraciones


async def test_cuerpo_alterado(cliente, equipo, firmador, monkeypatch):
    """Cambiar el cuerpo después de firmar se rechaza."""
    _modo(monkeypatch, "signature")
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO)

    r = await _latido(cliente, cab, cuerpo=b'{"session_id":"00000000-0000-0000-0000-000000000000"}')

    assert r.status_code == 401
    assert r.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_digest_recalculado_por_un_atacante(cliente, equipo, firmador, monkeypatch):
    """Aunque el atacante recalcule Content-Digest, la firma ya no coincide."""
    _modo(monkeypatch, "signature")
    otro = b'{"session_id":"00000000-0000-0000-0000-000000000000"}'
    cab = {**firmador.cabeceras("POST", BASE + LATIDO, CUERPO), "Content-Digest": firma.content_digest(otro)}

    r = await _latido(cliente, cab, cuerpo=otro)

    assert r.status_code == 401


async def test_url_alterada(cliente, equipo, firmador, monkeypatch):
    """Una firma hecha para otra ruta no sirve."""
    _modo(monkeypatch, "signature")
    cab = firmador.cabeceras("POST", BASE + "/api/v1/machine/sessions/current/end", CUERPO)

    r = await _latido(cliente, cab)

    assert r.status_code == 401


async def test_metodo_alterado(cliente, equipo, firmador, monkeypatch):
    """Una firma de GET no sirve para un POST."""
    _modo(monkeypatch, "signature")

    r = await _latido(cliente, firmador.cabeceras("GET", BASE + LATIDO), cuerpo=b"")

    assert r.status_code == 401


async def test_repeticion(cliente, equipo, firmador, monkeypatch):
    """La misma petición firmada dos veces: la segunda se rechaza."""
    _modo(monkeypatch, "signature")
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO)

    primera = await _latido(cliente, cab)
    segunda = await _latido(cliente, cab)

    assert primera.status_code == 200
    assert segunda.status_code == 401
    assert segunda.json()["code"] == "MACHINE_SIGNATURE_INVALID"


@pytest.mark.parametrize("desfase", [-31, 31])
async def test_reloj_desfasado(cliente, equipo, firmador, monkeypatch, desfase):
    """Fuera de ±30 s responde ``MACHINE_CLOCK_SKEW`` (el equipo corrige con ``Date``)."""
    _modo(monkeypatch, "signature")
    cab = firmador.cabeceras("POST", BASE + LATIDO, CUERPO, created=int(time.time()) + desfase)

    r = await _latido(cliente, cab)

    assert r.status_code == 401
    assert r.json()["code"] == "MACHINE_CLOCK_SKEW"


async def test_algoritmo_no_permitido(cliente, equipo, firmador, monkeypatch):
    """Solo se acepta ``ecdsa-p256-sha256``."""
    _modo(monkeypatch, "signature")

    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO, alg="hmac-sha256"))

    assert r.status_code == 401


async def test_clave_desconocida(cliente, equipo, monkeypatch):
    """Una firma válida de una clave que no está enrolada se rechaza."""
    _modo(monkeypatch, "signature")
    intruso = Firmador()

    r = await _latido(cliente, intruso.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == 401


async def test_cuerpo_sin_content_digest_firmado(cliente, equipo, firmador, monkeypatch):
    """Si hay cuerpo, la firma debe cubrir ``content-digest``."""
    _modo(monkeypatch, "signature")
    cab = firmador.cabeceras("POST", BASE + LATIDO)  # firmada como si no hubiera cuerpo

    r = await _latido(cliente, cab)

    assert r.status_code == 401


# ---------------------------------------------------------------- estado del equipo


@pytest.mark.parametrize(
    ("estado", "status", "code"),
    [(MachineStatus.disabled, 403, "MACHINE_DISABLED"),
     (MachineStatus.pending_enrollment, 401, "MACHINE_SIGNATURE_INVALID")],
)
async def test_equipo_no_activo(cliente, sesiones, equipo, firmador, monkeypatch, estado, status, code):
    """Solo los equipos activos pueden firmar."""
    _modo(monkeypatch, "signature")
    async with sesiones() as db:
        (await db.get(Machine, equipo.id)).status = estado
        await db.commit()

    r = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))

    assert r.status_code == status
    assert r.json()["code"] == code


# ---------------------------------------------------------------- modos


CREDENCIAL = {"X-Machine-Code": "LAB-TEST-PC01", "X-Machine-Key": "clave-pc01"}


async def test_modo_signature_rechaza_la_credencial(cliente, equipo, monkeypatch):
    """En ``signature`` la credencial provisional ya no basta."""
    _modo(monkeypatch, "signature")

    r = await _latido(cliente, CREDENCIAL)

    assert r.status_code == 401


async def test_modo_dual_acepta_la_credencial(cliente, equipo, monkeypatch):
    """En ``dual`` un equipo sin firma sigue funcionando con la credencial."""
    _modo(monkeypatch, "dual")

    r = await _latido(cliente, CREDENCIAL)

    assert r.status_code == 200


async def test_modo_dual_exige_que_la_firma_sea_valida(cliente, equipo, firmador, monkeypatch):
    """En ``dual``, una firma inválida no se salva con la credencial."""
    _modo(monkeypatch, "dual")
    cab = {**CREDENCIAL, **firmador.cabeceras("POST", BASE + "/otra/ruta", CUERPO)}

    r = await _latido(cliente, cab)

    assert r.status_code == 401


async def test_modo_dual_con_token_y_firma_validos(cliente, equipo, firmador, monkeypatch):
    """En ``dual`` el PC envía las dos cosas y se acepta."""
    _modo(monkeypatch, "dual")

    r = await _latido(cliente, {**CREDENCIAL, **firmador.cabeceras("POST", BASE + LATIDO, CUERPO)})

    assert r.status_code == 200


async def test_modo_token_ignora_la_firma(cliente, equipo, firmador, monkeypatch):
    """En ``token`` solo cuenta la credencial."""
    _modo(monkeypatch, "token")

    solo_firma = await _latido(cliente, firmador.cabeceras("POST", BASE + LATIDO, CUERPO))
    con_credencial = await _latido(cliente, CREDENCIAL)

    assert solo_firma.status_code == 401
    assert con_credencial.status_code == 200


# ---------------------------------------------------------------- salida transitoria de los retos


@pytest.mark.parametrize(
    ("activa", "entorno", "esperado"),
    [(False, "dev", 401), (True, "dev", 201), (True, "prod", 401)],
    ids=["apagada", "encendida-en-dev", "ignorada-en-prod"],
)
async def test_retos_solo_con_codigo(cliente, equipo, monkeypatch, activa, entorno, esperado):
    """``RETOS_ACEPTAN_SOLO_CODIGO`` deja pedir QR sin credencial, nunca en producción."""
    monkeypatch.setattr(settings, "retos_aceptan_solo_codigo", activa)
    monkeypatch.setattr(settings, "app_env", entorno)

    r = await cliente.post("/api/v1/machine/challenges", headers={"X-Machine-Code": "LAB-TEST-PC01"})

    assert r.status_code == esperado


async def test_la_salida_transitoria_no_abre_otras_rutas(cliente, equipo, monkeypatch):
    """Con el interruptor encendido, el latido sigue exigiendo credencial o firma."""
    monkeypatch.setattr(settings, "retos_aceptan_solo_codigo", True)
    monkeypatch.setattr(settings, "app_env", "dev")

    r = await _latido(cliente, {"X-Machine-Code": "LAB-TEST-PC01"})

    assert r.status_code == 401


async def test_la_salida_transitoria_no_salva_una_clave_mala(cliente, equipo, monkeypatch):
    """Si llega X-Machine-Key, se valida aunque el interruptor esté encendido."""
    monkeypatch.setattr(settings, "retos_aceptan_solo_codigo", True)
    monkeypatch.setattr(settings, "app_env", "dev")

    r = await cliente.post(
        "/api/v1/machine/challenges", headers={"X-Machine-Code": "LAB-TEST-PC01", "X-Machine-Key": "mala"}
    )

    assert r.status_code == 401


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
