"""Pruebas de integración de ``POST /machine/enroll`` (SEC-05, #110).

Cubren el camino feliz (el equipo queda activo, con su JWK, su huella y una
credencial que sirve para ``require_machine``) y los rechazos del contrato
v0.2.1: código inexistente, usado o vencido, firma inválida, JWK inválido,
equipo deshabilitado y clave repetida.
"""

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
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
from app.security.dependencies import hash_machine_credential
from app.services import enrolamiento

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


async def test_enrolar_activa_el_equipo_y_entrega_la_credencial(cliente, sesiones, pendiente):
    """El equipo queda activo con su JWK y su huella; la credencial solo como hash."""
    equipo = Equipo()
    codigo = await _codigo(sesiones, pendiente)

    resp = await cliente.post(RUTA, json=equipo.cuerpo(codigo, hostname="PC09", app_version="1.0.0"))

    assert resp.status_code == 201
    cuerpo = resp.json()
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
    assert machine.credential_hash == hash_machine_credential(cuerpo["provisional_credential"])
    assert cuerpo["provisional_credential"] not in str(machine.credential_hash)
    assert machine.enrolled_at is not None
    assert (machine.hostname, machine.app_version) == ("PC09", "1.0.0")

    async with sesiones() as db:
        usado = await db.scalar(select(EnrollmentCode.used_at))
        auditoria = (await db.scalars(select(AuditLog))).all()
    assert usado is not None
    assert [a.action for a in auditoria] == ["machine.enroll"]
    assert auditoria[0].metadata_info["keyid"] == cuerpo["keyid"]
    assert cuerpo["provisional_credential"] not in str(auditoria[0].metadata_info)


async def test_la_credencial_del_enrolamiento_autentica_al_equipo(cliente, sesiones, pendiente):
    """``require_machine`` acepta la credencial devuelta (se prueba con el latido)."""
    equipo = Equipo()
    resp = await cliente.post(RUTA, json=equipo.cuerpo(await _codigo(sesiones, pendiente)))
    credencial = resp.json()["provisional_credential"]

    latido = await cliente.post(
        "/api/v1/machine/heartbeat",
        headers={"X-Machine-Code": "LAB-TEST-PC09", "X-Machine-Key": credencial},
    )
    rechazo = await cliente.post(
        "/api/v1/machine/heartbeat",
        headers={"X-Machine-Code": "LAB-TEST-PC09", "X-Machine-Key": "otra-credencial"},
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
    assert machine.credential_hash == hash_machine_credential(r2.json()["provisional_credential"])


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
