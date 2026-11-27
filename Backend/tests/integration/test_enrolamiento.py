"""Pruebas de integración de ``POST /machine/enroll`` (SEC-05, #110).

Cubren el camino feliz (el equipo queda activo, con su JWK y su huella, y su
firma sirve para ``require_machine``) y los rechazos del contrato
v0.2.1: código inexistente, usado o vencido, firma inválida, JWK inválido,
equipo deshabilitado y clave repetida.
"""

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import sha256_digest
from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AuditLog,
    EnrollmentCode,
    Machine,
    MachineMode,
    MachineStatus,
    User,
    UserRole,
    UserStatus,
)
from app.security import firma
from app.services import enrolamiento
from tests.firmador import FirmaEquipo, Firmador

RUTA = "/api/v1/machine/enroll"


def _b64(datos: bytes) -> str:
    """Codifica en base64url sin relleno.

    Args:
        datos: Bytes que se codifican.

    Returns:
        Texto base64url sin ``=``.
    """
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


class Equipo:
    """Par P-256 de un equipo de prueba, con su JWK y su firmador ``r||s``."""

    def __init__(self) -> None:
        """Genera un par de claves P-256 nuevo."""
        self.clave = ec.generate_private_key(ec.SECP256R1())
        numeros = self.clave.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64(numeros.x.to_bytes(32, "big")),
            "y": _b64(numeros.y.to_bytes(32, "big")),
        }

    def firmar(self, mensaje: str) -> str:
        """Firma el mensaje como lo hace el escritorio: ECDSA P-256 en ``r||s``.

        Args:
            mensaje: Texto que se firma (el código de enrolamiento).

        Returns:
            Firma de 64 bytes en base64url sin relleno.
        """
        der = self.clave.sign(mensaje.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    def cuerpo(self, codigo: str, **cambios: object) -> dict:
        """Arma un cuerpo de enrolamiento válido para el código.

        Args:
            codigo: Código de un solo uso.
            **cambios: Campos que se sobrescriben o se agregan.

        Returns:
            Diccionario listo para enviar como JSON.
        """
        cuerpo = {"enrollment_code": codigo, "jwk": dict(self.jwk), "proof": self.firmar(codigo)}
        cuerpo.update(cambios)
        return cuerpo


def _entero(valor: int) -> str:
    """Codifica un entero de un JWK RSA: big-endian, sin ceros a la izquierda.

    Args:
        valor: Entero positivo.

    Returns:
        Texto base64url sin ``=``.
    """
    return _b64(valor.to_bytes((valor.bit_length() + 7) // 8, "big"))


class EquipoRsa(Equipo):
    """Par RSA como la clave del TPM de ST-DSK-01: firma ``SHA256withRSA``."""

    def __init__(self, bits: int = 2048, exponente: int = 65537) -> None:
        """Genera un par RSA nuevo.

        Args:
            bits: Tamaño del módulo.
            exponente: Exponente público.
        """
        self.clave = rsa.generate_private_key(public_exponent=exponente, key_size=bits)
        numeros = self.clave.public_key().public_numbers()
        self.jwk = {"kty": "RSA", "n": _entero(numeros.n), "e": _entero(numeros.e)}

    def firmar(self, mensaje: str) -> str:
        """Firma el mensaje como SunMSCAPI: RSASSA-PKCS1-v1_5 con SHA-256.

        Args:
            mensaje: Texto que se firma (el código de enrolamiento).

        Returns:
            Firma del largo del módulo en base64url sin relleno.
        """
        return _b64(self.clave.sign(mensaje.encode(), padding.PKCS1v15(), hashes.SHA256()))


@pytest.fixture
async def cliente(sesiones):
    """Cliente HTTP contra la app, con la base de pruebas inyectada."""

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def pendiente(sesiones, datos) -> Machine:
    """Equipo nuevo, pendiente de enrolar, en la sala de pruebas."""
    async with sesiones() as db:
        machine = Machine(code="LAB-TEST-PC09", lab_id=datos.lab.id, mode=MachineMode.kiosk)
        db.add(machine)
        await db.commit()
    return machine


async def _codigo(sesiones, machine: Machine, *, vence_en: timedelta = timedelta(hours=24),
                  usado: bool = False) -> str:
    """Crea un código de enrolamiento para el equipo, como la semilla de dev.

    Args:
        sesiones: Fábrica de sesiones de la base de pruebas.
        machine: Equipo dueño del código.
        vence_en: Tiempo hasta el vencimiento (negativo: ya venció).
        usado: Si el código ya se usó.

    Returns:
        El código en claro.
    """
    codigo = f"ENR-{uuid.uuid4().hex[:12]}"
    ahora = datetime.now(UTC)
    async with sesiones() as db:
        admin = await db.scalar(select(User).where(User.role == UserRole.admin))
        if admin is None:
            admin = User(
                email_ct=b"admin@test.invalid", email_bidx=uuid.uuid4().bytes,
                full_name_ct=b"Admin", password_hash="no-es-un-hash", role=UserRole.admin,
                status=UserStatus.active, privacy_consent_at=ahora,
            )
            db.add(admin)
            await db.flush()
        db.add(EnrollmentCode(
            machine_id=machine.id, code_hash=sha256_digest(codigo), created_by=admin.id,
            expires_at=ahora + vence_en, used_at=ahora if usado else None,
        ))
        await db.commit()
    return codigo


async def _equipo(sesiones, machine_id) -> Machine:
    """Lee el equipo desde la base.

    Args:
        sesiones: Fábrica de sesiones de la base de pruebas.
        machine_id: Id del equipo.

    Returns:
        El equipo con sus valores actuales.
    """
    async with sesiones() as db:
        return await db.get(Machine, machine_id)


# ---------------------------------------------------------------- camino feliz


async def test_enrolar_activa_el_equipo_sin_entregar_credencial(cliente, sesiones, pendiente):
    """El equipo queda activo con su JWK y su huella; la respuesta no trae ninguna credencial."""
    equipo = Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, hostname="PC09", app_version="1.0.0"))

    assert resp.status_code == 201
    cuerpo = resp.json()
    assert set(cuerpo) == {"machine_id", "code", "lab", "mode", "keyid"}
    assert cuerpo["machine_id"] == str(pendiente.id)
    assert cuerpo["code"] == "LAB-TEST-PC09"
    assert cuerpo["lab"] == "Sala de pruebas"
    assert cuerpo["mode"] == "kiosk"
    assert cuerpo["keyid"] == enrolamiento.huella_jwk(equipo.jwk)
    assert resp.headers["cache-control"] == "no-store"

    machine = await _equipo(sesiones, pendiente.id)
    assert machine.status == MachineStatus.active
    assert machine.public_key_jwk == equipo.jwk
    assert machine.key_thumbprint == cuerpo["keyid"]
    assert machine.enrolled_at is not None
    assert (machine.hostname, machine.app_version) == ("PC09", "1.0.0")

    async with sesiones() as db:
        usado = await db.scalar(select(EnrollmentCode.used_at))
        auditoria = (await db.scalars(select(AuditLog))).all()
    assert usado is not None
    assert [a.action for a in auditoria] == ["machine.enroll"]
    assert auditoria[0].metadata_info["keyid"] == cuerpo["keyid"]


async def test_la_clave_enrolada_autentica_al_equipo(cliente, sesiones, pendiente):
    """La firma de la clave enrolada sirve para el latido; un token responde 401."""
    firmador = Firmador()
    equipo = Equipo()
    equipo.clave, equipo.jwk = firmador.clave, firmador.jwk
    resp = await cliente.post(RUTA, json=equipo.cuerpo(await _codigo(sesiones, pendiente)))
    assert resp.status_code == 201

    latido = await cliente.post("/api/v1/machine/heartbeat", auth=FirmaEquipo(firmador))
    rechazo = await cliente.post(
        "/api/v1/machine/heartbeat",
        headers={"X-Machine-Code": "LAB-TEST-PC09", "X-Machine-Key": "token-ficticio"},
    )

    assert latido.status_code == 200
    assert latido.json()["mode"] == "kiosk"
    assert rechazo.status_code == 401
    assert rechazo.json()["code"] == "MACHINE_SIGNATURE_INVALID"


async def test_reenrolar_con_un_codigo_nuevo_reemplaza_la_clave(cliente, sesiones, pendiente):
    """Un equipo activo puede cambiar de clave con un código nuevo del administrador."""
    primero, segundo = Equipo(), Equipo()
    r1 = await cliente.post(RUTA, json=primero.cuerpo(await _codigo(sesiones, pendiente)))
    r2 = await cliente.post(RUTA, json=segundo.cuerpo(await _codigo(sesiones, pendiente)))

    assert r1.status_code == r2.status_code == 201
    machine = await _equipo(sesiones, pendiente.id)
    assert machine.key_thumbprint == r2.json()["keyid"] != r1.json()["keyid"]


# ---------------------------------------------------------------- clave RSA del TPM (ST-SEC-04)


async def test_enrolar_con_clave_rsa_del_tpm(cliente, sesiones, pendiente):
    """Una clave RSA 2048 (la del TPM) se enrola y queda guardada con su huella RFC 7638."""
    equipo = EquipoRsa()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo))

    assert resp.status_code == 201
    keyid = resp.json()["keyid"]
    assert keyid == enrolamiento.huella_jwk(equipo.jwk)
    machine = await _equipo(sesiones, pendiente.id)
    assert machine.status == MachineStatus.active
    assert machine.public_key_jwk == equipo.jwk
    assert machine.key_thumbprint == keyid
    async with sesiones() as db:
        auditoria = await db.scalar(select(AuditLog))
    assert auditoria.metadata_info["kty"] == "RSA"


def test_huella_rsa_de_rfc_7638():
    """La huella de un JWK RSA es la del ejemplo de RFC 7638 §3.1."""
    n = (
        "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECP"
        "ebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY"
        "368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0f"
        "M4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
    )
    jwk = {"kty": "RSA", "n": n, "e": "AQAB"}

    assert enrolamiento.huella_jwk(jwk) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"
    assert enrolamiento.jwk_publico({**jwk, "alg": "RS256"}) == jwk


async def test_clave_rsa_con_firma_de_otra_clave_responde_401(cliente, sesiones, pendiente):
    """La prueba RSA debe ser de la misma clave; si no, el código no se quema."""
    equipo, intruso = EquipoRsa(), EquipoRsa()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, proof=intruso.firmar(codigo)))
    reintento = await cliente.post(RUTA, json=equipo.cuerpo(codigo))

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"
    assert reintento.status_code == 201


async def test_clave_rsa_con_prueba_ecdsa_responde_401(cliente, sesiones, pendiente):
    """No se mezclan tipos: una prueba ``r||s`` no sirve para una clave RSA."""
    equipo = EquipoRsa()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, proof=Equipo().firmar(codigo)))

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"


@pytest.mark.parametrize(
    "cambio",
    [
        {"d": _b64(b"\x01" * 256)},
        {"p": _b64(b"\x01" * 128)},
        {"e": "AQAA"},
        {"n": "!" * 342},
        {"crv": "P-256"},
    ],
    ids=["con-d", "con-primo", "exponente-distinto", "n-no-base64url", "miembro-extra"],
)
async def test_jwk_rsa_invalido_responde_422(cliente, sesiones, pendiente, cambio):
    """El JWK RSA debe ser público, sin miembros extra, con base64url y e = 65537."""
    equipo = EquipoRsa()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, jwk={**equipo.jwk, **cambio}))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_clave_rsa_menor_de_2048_bits_responde_422(cliente, sesiones, pendiente):
    """Una clave RSA de 1024 bits se rechaza aunque la prueba sea válida."""
    equipo = EquipoRsa(bits=1024)
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo))

    assert resp.status_code == 422
    assert (await _equipo(sesiones, pendiente.id)).status == MachineStatus.pending_enrollment


def test_validacion_rsa_en_el_servicio():
    """El servicio rechaza lo que el esquema no alcanza a ver: tamaño y ceros a la izquierda."""
    equipo = EquipoRsa()
    with pytest.raises(ValueError, match="65537"):
        enrolamiento.clave_publica_desde_jwk({**equipo.jwk, "e": _entero(3)})
    with pytest.raises(ValueError, match="ceros"):
        enrolamiento.clave_publica_desde_jwk({**equipo.jwk, "n": _b64(b"\x00" + _b64d(equipo.jwk["n"]))})
    with pytest.raises(ValueError, match="bits"):
        enrolamiento.clave_publica_desde_jwk({"kty": "RSA", "n": _entero(2**5000 + 1), "e": "AQAB"})
    with pytest.raises(ValueError, match="EC P-256 o RSA"):
        enrolamiento.clave_publica_desde_jwk({"kty": "OKP"})


@pytest.mark.parametrize("bits", [2056, 2560])
async def test_tamano_rsa_intermedio_responde_422(cliente, sesiones, pendiente, bits):
    """Un tamaño con el que luego no se podría firmar se rechaza al enrolar."""
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=EquipoRsa(bits=bits).cuerpo(codigo))

    assert resp.status_code == 422
    assert (await _equipo(sesiones, pendiente.id)).status == MachineStatus.pending_enrollment


def test_los_tamanos_rsa_coinciden_con_los_de_la_firma():
    """Todo tamaño que se enrola tiene un largo de firma que el verificador acepta."""
    assert {bits // 8 for bits in enrolamiento.RSA_BITS} <= firma._LARGOS_FIRMA


@pytest.mark.parametrize("bits", [2048, 3072, 4096])
async def test_tamanos_rsa_admitidos(cliente, sesiones, pendiente, bits):
    """Los tres tamaños del contrato se enrolan."""
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=EquipoRsa(bits=bits).cuerpo(codigo))

    assert resp.status_code == 201


@pytest.mark.parametrize(
    ("clase", "campo", "relleno"),
    [(EquipoRsa, "n", "=="), (Equipo, "x", "="), (Equipo, "y", "=")],
    ids=["rsa-n", "ec-x", "ec-y"],
)
async def test_el_relleno_no_permite_enrolar_la_misma_clave_en_dos_equipos(
    cliente, sesiones, datos, pendiente, clase, campo, relleno
):
    """La misma clave escrita con ``=`` daría otra huella: se rechaza con 422."""
    equipo = clase()
    primero = await cliente.post(RUTA, json=equipo.cuerpo(await _codigo(sesiones, pendiente)))
    codigo = await _codigo(sesiones, datos.pc02)

    con_relleno = await cliente.post(
        RUTA, json=equipo.cuerpo(codigo, jwk={**equipo.jwk, campo: equipo.jwk[campo] + relleno})
    )
    sin_relleno = await cliente.post(RUTA, json=equipo.cuerpo(codigo))

    assert primero.status_code == 201
    assert con_relleno.status_code == 422
    assert sin_relleno.status_code == 409


@pytest.mark.parametrize("clase", [Equipo, EquipoRsa], ids=["ec", "rsa"])
def test_los_bits_sobrantes_no_cambian_la_huella(clase):
    """Un último carácter con bits sobrantes decodifica igual, pero no es canónico."""
    alfabeto = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    jwk = clase().jwk
    campo = "n" if jwk["kty"] == "RSA" else "x"
    ultimo = alfabeto[alfabeto.index(jwk[campo][-1]) + 1]
    alterado = jwk[campo][:-1] + ultimo

    assert _b64d(alterado) == _b64d(jwk[campo])
    with pytest.raises(ValueError, match="base64url"):
        enrolamiento.clave_publica_desde_jwk({**jwk, campo: alterado})


def _b64d(valor: str) -> bytes:
    """Decodifica base64url sin relleno.

    Args:
        valor: Texto base64url.

    Returns:
        Los bytes.
    """
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


# ---------------------------------------------------------------- código


@pytest.mark.parametrize("caso", ["inexistente", "usado", "vencido"])
async def test_codigo_invalido_responde_401(cliente, sesiones, pendiente, caso):
    """Código inexistente, usado o vencido → ``ENROLLMENT_CODE_INVALID``; el equipo no cambia."""
    if caso == "inexistente":
        codigo = "ENR-no-existe-000"
    else:
        codigo = await _codigo(
            sesiones, pendiente, usado=caso == "usado",
            vence_en=timedelta(seconds=-1) if caso == "vencido" else timedelta(hours=24),
        )

    resp = await cliente.post(RUTA, json=Equipo().cuerpo(codigo))

    assert resp.status_code == 401
    assert resp.json()["code"] == "ENROLLMENT_CODE_INVALID"
    assert codigo not in resp.text
    assert (await _equipo(sesiones, pendiente.id)).status == MachineStatus.pending_enrollment


async def test_el_codigo_es_de_un_solo_uso(cliente, sesiones, pendiente):
    """El segundo enrolamiento con el mismo código se rechaza."""
    codigo = await _codigo(sesiones, pendiente)

    primero = await cliente.post(RUTA, json=Equipo().cuerpo(codigo))
    segundo = await cliente.post(RUTA, json=Equipo().cuerpo(codigo))

    assert primero.status_code == 201
    assert segundo.status_code == 401
    assert segundo.json()["code"] == "ENROLLMENT_CODE_INVALID"


# ---------------------------------------------------------------- prueba de posesión


async def test_firma_de_otra_clave_responde_401_y_no_quema_el_codigo(cliente, sesiones, pendiente):
    """Una prueba firmada con otra clave se rechaza y el código sigue sirviendo."""
    equipo, intruso = Equipo(), Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, proof=intruso.firmar(codigo)))
    reintento = await cliente.post(RUTA, json=equipo.cuerpo(codigo))

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"
    assert reintento.status_code == 201


async def test_firma_de_otro_mensaje_responde_401(cliente, sesiones, pendiente):
    """La prueba debe firmar exactamente el código enviado."""
    equipo = Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, proof=equipo.firmar(codigo + "x")))

    assert resp.status_code == 401
    assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"


# ---------------------------------------------------------------- JWK y cuerpo


@pytest.mark.parametrize(
    "cambio",
    [
        {"d": _b64(b"\x01" * 32)},
        {"crv": "P-384"},
        {"kty": "RSA"},
        {"x": _b64(b"\x00" * 32)},
        {"y": "no-es-base64url-valido-en-absoluto-!!!!!!!!"},
    ],
    ids=["con-parte-privada", "otra-curva", "otro-tipo", "fuera-de-la-curva", "no-base64url"],
)
async def test_jwk_invalido_responde_422(cliente, sesiones, pendiente, cambio):
    """El JWK debe ser una clave pública EC P-256 válida."""
    equipo = Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, jwk={**equipo.jwk, **cambio}))

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_campos_desconocidos_responden_422(cliente, sesiones, pendiente):
    """El cuerpo rechaza campos que no están en el contrato."""
    equipo = Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, machine_id=str(uuid.uuid4())))

    assert resp.status_code == 422


# ---------------------------------------------------------------- estado del equipo


async def test_equipo_deshabilitado_responde_403(cliente, sesiones, pendiente):
    """Un equipo deshabilitado no se puede enrolar."""
    codigo = await _codigo(sesiones, pendiente)
    async with sesiones() as db:
        (await db.get(Machine, pendiente.id)).status = MachineStatus.disabled
        await db.commit()

    resp = await cliente.post(RUTA, json=Equipo().cuerpo(codigo))

    assert resp.status_code == 403
    assert resp.json()["code"] == "MACHINE_DISABLED"


async def test_clave_ya_registrada_por_otro_equipo_responde_409(cliente, sesiones, datos, pendiente):
    """Dos equipos no pueden compartir la misma clave pública."""
    equipo = Equipo()
    async with sesiones() as db:
        otro = await db.get(Machine, datos.pc01.id)
        otro.key_thumbprint = enrolamiento.huella_jwk(equipo.jwk)
        await db.commit()

    resp = await cliente.post(RUTA, json=equipo.cuerpo(await _codigo(sesiones, pendiente)))

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"
