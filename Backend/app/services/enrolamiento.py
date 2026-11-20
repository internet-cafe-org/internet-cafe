"""Enrolamiento de un equipo con su clave pública (SEC-05, SRS §8.4 y §12.4).

El equipo envía un código de un solo uso, su clave pública P-256 en JWK y una
prueba de posesión: la firma ECDSA P-256 / SHA-256 de los bytes UTF-8 del
código, en formato ``r||s`` de 64 bytes y base64url sin relleno. Si todo es
válido, el equipo queda ``active`` con su JWK, su huella RFC 7638 (el ``keyid``
de la firma RFC 9421) y una credencial provisional que solo se guarda como hash.
"""

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.crypto import sha256_digest
from app.models import AuditActorType, EnrollmentCode, Lab, Machine, MachineMode, MachineStatus
from app.security.dependencies import hash_machine_credential

_LARGO_COORDENADA = 32
_LARGO_FIRMA = 64


class CodigoInvalido(Exception):
    """Código de enrolamiento inexistente, usado o vencido."""


class FirmaInvalida(Exception):
    """La prueba de posesión no corresponde a la clave enviada."""


class EquipoDeshabilitado(Exception):
    """El equipo del código está deshabilitado."""


class ClaveEnUso(Exception):
    """Otro equipo ya registró esa misma clave pública."""


@dataclass(frozen=True)
class Enrolamiento:
    """Resultado de un enrolamiento exitoso."""

    machine_id: uuid.UUID
    code: str
    lab: str | None
    mode: MachineMode
    keyid: str
    provisional_credential: str


def _b64url_decodificar(valor: str) -> bytes:
    """Decodifica base64url sin relleno (RFC 7515 §2).

    Args:
        valor: Texto en base64url, con o sin ``=`` al final.

    Returns:
        Los bytes decodificados.

    Raises:
        ValueError: Si el texto no es base64url válido.
    """
    if not valor or any(c in valor for c in "+/ \n"):
        raise ValueError("No es base64url.")
    relleno = "=" * (-len(valor.rstrip("=")) % 4)
    return base64.urlsafe_b64decode(valor.rstrip("=") + relleno)


def _b64url_codificar(datos: bytes) -> str:
    """Codifica en base64url sin relleno.

    Args:
        datos: Bytes que se codifican.

    Returns:
        Texto base64url sin ``=``.
    """
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def clave_publica_desde_jwk(jwk: dict) -> ec.EllipticCurvePublicKey:
    """Valida un JWK EC P-256 público y lo convierte en clave de ``cryptography``.

    Args:
        jwk: Diccionario con ``kty``, ``crv``, ``x`` e ``y``.

    Returns:
        La clave pública lista para verificar firmas.

    Raises:
        ValueError: Si no es EC P-256, incluye la parte privada (``d``), las
            coordenadas no miden 32 bytes o el punto no está en la curva.
    """
    if "d" in jwk:
        raise ValueError("El JWK no puede incluir la parte privada.")
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("El JWK debe ser EC P-256.")
    try:
        x = _b64url_decodificar(jwk["x"])
        y = _b64url_decodificar(jwk["y"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Las coordenadas del JWK no son base64url.") from None
    if len(x) != _LARGO_COORDENADA or len(y) != _LARGO_COORDENADA:
        raise ValueError("Las coordenadas del JWK deben medir 32 bytes.")
    numeros = ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
    )
    try:
        return numeros.public_key()
    except ValueError:
        raise ValueError("El punto del JWK no está en la curva P-256.") from None


def huella_jwk(jwk: dict) -> str:
    """Calcula la huella RFC 7638 de un JWK EC.

    Usa solo los miembros obligatorios (``crv``, ``kty``, ``x``, ``y``) en orden
    lexicográfico y sin espacios, y devuelve el SHA-256 en base64url.

    Args:
        jwk: JWK EC P-256 ya validado.

    Returns:
        Huella de 43 caracteres; es el ``keyid`` de la firma RFC 9421.
    """
    canonico = json.dumps(
        {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return _b64url_codificar(hashlib.sha256(canonico.encode("utf-8")).digest())


def verificar_prueba(clave: ec.EllipticCurvePublicKey, codigo: str, prueba: str) -> None:
    """Verifica la prueba de posesión: la firma ``r||s`` del código.

    Args:
        clave: Clave pública del equipo.
        codigo: Código de enrolamiento, tal como lo envió el equipo.
        prueba: Firma ECDSA P-256 / SHA-256 en ``r||s`` y base64url.

    Raises:
        FirmaInvalida: Si la firma no es válida para ese código y esa clave.
    """
    try:
        crudo = _b64url_decodificar(prueba)
    except ValueError:
        raise FirmaInvalida() from None
    if len(crudo) != _LARGO_FIRMA:
        raise FirmaInvalida()
    r = int.from_bytes(crudo[:32], "big")
    s = int.from_bytes(crudo[32:], "big")
    try:
        clave.verify(encode_dss_signature(r, s), codigo.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise FirmaInvalida() from None


async def enrolar(
    db: AsyncSession,
    *,
    codigo: str,
    jwk: dict,
    prueba: str,
    hostname: str | None = None,
    app_version: str | None = None,
    now: datetime | None = None,
) -> Enrolamiento:
    """Enrola el equipo dueño del código y confirma la transacción.

    El código se bloquea con ``FOR UPDATE`` para que dos enrolamientos con el
    mismo código no ganen los dos. Solo se marca como usado si la prueba de
    posesión es válida, así un error de firma no quema el código.

    Args:
        db: Sesión de base de datos.
        codigo: Código de un solo uso que entregó el administrador.
        jwk: Clave pública P-256 del equipo, ya validada por el esquema.
        prueba: Firma ``r||s`` del código en base64url.
        hostname: Nombre del equipo en la red, si lo envía.
        app_version: Versión de la aplicación de escritorio, si la envía.
        now: Hora actual; solo para las pruebas.

    Returns:
        Los datos del equipo y la credencial provisional en claro (una sola vez).

    Raises:
        CodigoInvalido: Si el código no existe, ya se usó o venció.
        FirmaInvalida: Si la prueba de posesión no es válida.
        EquipoDeshabilitado: Si el equipo del código está deshabilitado.
        ClaveEnUso: Si otro equipo ya registró la misma clave.
    """
    ahora = now or datetime.now(UTC)
    clave = clave_publica_desde_jwk(jwk)

    registro = await db.scalar(
        select(EnrollmentCode)
        .where(EnrollmentCode.code_hash == sha256_digest(codigo))
        .with_for_update()
    )
    if registro is None or registro.used_at is not None or registro.expires_at <= ahora:
        raise CodigoInvalido()

    verificar_prueba(clave, codigo, prueba)

    machine = await db.get(Machine, registro.machine_id, with_for_update=True)
    if machine is None:
        raise CodigoInvalido()
    if machine.status == MachineStatus.disabled:
        raise EquipoDeshabilitado()

    keyid = huella_jwk(jwk)
    otro = await db.scalar(
        select(Machine.id).where(Machine.key_thumbprint == keyid, Machine.id != machine.id)
    )
    if otro is not None:
        raise ClaveEnUso()

    credencial = secrets.token_urlsafe(32)
    machine.public_key_jwk = {k: jwk[k] for k in ("kty", "crv", "x", "y")}
    machine.key_thumbprint = keyid
    machine.credential_hash = hash_machine_credential(credencial)
    machine.status = MachineStatus.active
    machine.enrolled_at = ahora
    machine.hostname = hostname or machine.hostname
    machine.app_version = app_version or machine.app_version
    registro.used_at = ahora

    lab = await db.get(Lab, machine.lab_id) if machine.lab_id else None
    await audit(
        db,
        AuditActorType.machine,
        "machine.enroll",
        actor_id=machine.id,
        target_type="machine",
        target_id=machine.id,
        metadata_info={"keyid": keyid, "enrollment_code_id": str(registro.id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ClaveEnUso() from None

    return Enrolamiento(
        machine_id=machine.id,
        code=machine.code,
        lab=lab.name if lab else None,
        mode=machine.mode,
        keyid=keyid,
        provisional_credential=credencial,
    )
