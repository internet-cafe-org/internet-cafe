"""Enrolamiento de un equipo con su clave pública (SEC-05, SRS §8.4 y §12.4).

El equipo envía un código de un solo uso, su clave pública en JWK y una prueba
de posesión: la firma de los bytes UTF-8 del código en base64url sin relleno.
Se aceptan dos tipos de clave:

- EC P-256 (la clave PKCS12 de DSK-03a): firma ECDSA P-256 / SHA-256 en formato
  ``r||s`` de 64 bytes.
- RSA de 2048 a 4096 bits (la clave no exportable del TPM, HU-28 / ST-SEC-04):
  firma RSASSA-PKCS1-v1_5 / SHA-256, del largo del módulo (256 bytes con 2048).

Si todo es válido, el equipo queda ``active`` con su JWK, su huella RFC 7638 (el
``keyid`` de la firma RFC 9421) y una credencial provisional que solo se guarda
como hash.
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
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
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
RSA_BITS_MIN = 2048
RSA_BITS_MAX = 4096
_RSA_EXPONENTE = 65537

ClavePublica = ec.EllipticCurvePublicKey | rsa.RSAPublicKey

# Miembros públicos de cada tipo de JWK (RFC 7638 §3.2): son los que se guardan y
# los que entran en la huella, en orden lexicográfico.
MIEMBROS_PUBLICOS = {"EC": ("crv", "kty", "x", "y"), "RSA": ("e", "kty", "n")}


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


def _clave_ec(jwk: dict) -> ec.EllipticCurvePublicKey:
    """Valida un JWK EC P-256 público.

    Args:
        jwk: Diccionario con ``kty``, ``crv``, ``x`` e ``y``.

    Returns:
        La clave pública lista para verificar firmas.

    Raises:
        ValueError: Si no es P-256, las coordenadas no miden 32 bytes o el punto
            no está en la curva.
    """
    if jwk.get("crv") != "P-256":
        raise ValueError("El JWK EC debe ser P-256.")
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


def _clave_rsa(jwk: dict) -> rsa.RSAPublicKey:
    """Valida un JWK RSA público (clave del TPM, ST-SEC-04).

    Args:
        jwk: Diccionario con ``kty``, ``n`` y ``e``.

    Returns:
        La clave pública lista para verificar firmas.

    Raises:
        ValueError: Si ``n`` o ``e`` no son base64url, el módulo no mide entre
            2048 y 4096 bits o el exponente no es 65537.
    """
    if any(k in jwk for k in ("p", "q", "dp", "dq", "qi", "oth")):
        raise ValueError("El JWK no puede incluir la parte privada.")
    try:
        n_bytes = _b64url_decodificar(jwk["n"])
        e_bytes = _b64url_decodificar(jwk["e"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("El módulo o el exponente del JWK no son base64url.") from None
    if n_bytes[:1] == b"\x00" or e_bytes[:1] == b"\x00":
        # RFC 7518 §6.3.1: sin ceros a la izquierda, así la huella es única.
        raise ValueError("El módulo y el exponente no pueden tener ceros a la izquierda.")
    n = int.from_bytes(n_bytes, "big")
    e = int.from_bytes(e_bytes, "big")
    if not RSA_BITS_MIN <= n.bit_length() <= RSA_BITS_MAX:
        raise ValueError(f"La clave RSA debe medir entre {RSA_BITS_MIN} y {RSA_BITS_MAX} bits.")
    if e != _RSA_EXPONENTE:
        raise ValueError("El exponente de la clave RSA debe ser 65537.")
    try:
        return rsa.RSAPublicNumbers(e, n).public_key()
    except ValueError:
        raise ValueError("La clave RSA del JWK no es válida.") from None


def clave_publica_desde_jwk(jwk: dict) -> ClavePublica:
    """Valida un JWK público (EC P-256 o RSA) y lo convierte en clave de ``cryptography``.

    Args:
        jwk: JWK EC (``kty``, ``crv``, ``x``, ``y``) o RSA (``kty``, ``n``, ``e``).

    Returns:
        La clave pública lista para verificar firmas.

    Raises:
        ValueError: Si incluye la parte privada (``d``), el tipo no es ``EC`` ni
            ``RSA`` o la clave no cumple las reglas de su tipo.
    """
    if "d" in jwk:
        raise ValueError("El JWK no puede incluir la parte privada.")
    if jwk.get("kty") == "EC":
        return _clave_ec(jwk)
    if jwk.get("kty") == "RSA":
        return _clave_rsa(jwk)
    raise ValueError("El JWK debe ser EC P-256 o RSA.")


def jwk_publico(jwk: dict) -> dict:
    """Deja solo los miembros públicos del JWK, que son los que se guardan.

    Args:
        jwk: JWK ya validado.

    Returns:
        Copia con los miembros de RFC 7638 de su tipo.
    """
    return {k: jwk[k] for k in MIEMBROS_PUBLICOS[jwk["kty"]]}


def huella_jwk(jwk: dict) -> str:
    """Calcula la huella RFC 7638 de un JWK EC o RSA.

    Usa solo los miembros obligatorios del tipo (EC: ``crv``, ``kty``, ``x``,
    ``y``; RSA: ``e``, ``kty``, ``n``) en orden lexicográfico y sin espacios, y
    devuelve el SHA-256 en base64url.

    Args:
        jwk: JWK ya validado.

    Returns:
        Huella de 43 caracteres; es el ``keyid`` de la firma RFC 9421.
    """
    canonico = json.dumps(jwk_publico(jwk), separators=(",", ":"), sort_keys=True)
    return _b64url_codificar(hashlib.sha256(canonico.encode("utf-8")).digest())


def verificar_prueba(clave: ClavePublica, codigo: str, prueba: str) -> None:
    """Verifica la prueba de posesión: la firma del código con la clave enviada.

    Args:
        clave: Clave pública del equipo.
        codigo: Código de enrolamiento, tal como lo envió el equipo.
        prueba: Firma en base64url: ``r||s`` de 64 bytes (EC) o RSASSA-PKCS1-v1_5
            del largo del módulo (RSA), ambas con SHA-256.

    Raises:
        FirmaInvalida: Si la firma no es válida para ese código y esa clave.
    """
    try:
        crudo = _b64url_decodificar(prueba)
    except ValueError:
        raise FirmaInvalida() from None
    mensaje = codigo.encode("utf-8")
    try:
        if isinstance(clave, rsa.RSAPublicKey):
            if len(crudo) != (clave.key_size + 7) // 8:
                raise FirmaInvalida()
            clave.verify(crudo, mensaje, padding.PKCS1v15(), hashes.SHA256())
            return
        if len(crudo) != _LARGO_FIRMA:
            raise FirmaInvalida()
        r = int.from_bytes(crudo[:32], "big")
        s = int.from_bytes(crudo[32:], "big")
        clave.verify(encode_dss_signature(r, s), mensaje, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise FirmaInvalida() from None


def _codigo_vigente(registro: EnrollmentCode | None, ahora: datetime) -> bool:
    """Indica si el código existe, no se usó y no venció.

    Args:
        registro: Código leído de la base, si existe.
        ahora: Hora actual.

    Returns:
        ``True`` si todavía sirve para enrolar.
    """
    return registro is not None and registro.used_at is None and registro.expires_at > ahora


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

    Primero se bloquea el equipo y después el código (``FOR UPDATE``), el mismo orden
    de ``/admin/machines/{id}/revoke-key`` y ``enrollment-code``: así no hay
    interbloqueos y dos enrolamientos con el mismo código no ganan los dos. El código se
    vuelve a comprobar ya bloqueado. Solo se marca como usado si la prueba de posesión
    es válida, así un error de firma no quema el código.

    Args:
        db: Sesión de base de datos.
        codigo: Código de un solo uso que entregó el administrador.
        jwk: Clave pública EC P-256 o RSA del equipo, ya validada por el esquema.
        prueba: Firma del código en base64url (``r||s`` o RSASSA-PKCS1-v1_5).
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

    consulta = select(EnrollmentCode).where(EnrollmentCode.code_hash == sha256_digest(codigo))
    registro = await db.scalar(consulta)
    if not _codigo_vigente(registro, ahora):
        raise CodigoInvalido()

    verificar_prueba(clave, codigo, prueba)

    machine = await db.get(Machine, registro.machine_id, with_for_update=True)
    if machine is None:
        raise CodigoInvalido()
    # Mientras se esperaba el equipo, el código pudo usarse o invalidarse.
    registro = await db.scalar(
        consulta.with_for_update().execution_options(populate_existing=True)
    )
    if not _codigo_vigente(registro, ahora):
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
    machine.public_key_jwk = jwk_publico(jwk)
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
        metadata_info={"keyid": keyid, "kty": jwk["kty"], "enrollment_code_id": str(registro.id)},
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
