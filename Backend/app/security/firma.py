"""Verificación de la firma por petición del equipo (SEC-07a y SEC-07b, RFC 9421).

Perfil acordado en los vectores de SEC-08 (``contracts/test-vectors``):

- etiqueta ``sig1`` y algoritmo ``ecdsa-p256-sha256``; firma ``r||s`` de 64
  bytes en base64 (``Signature: sig1=:<base64>:``);
- componentes ``@method``, ``@target-uri`` y, solo si hay cuerpo,
  ``content-digest`` (RFC 9530, SHA-256 de los bytes del cuerpo);
- parámetros ``created``, ``keyid`` (huella RFC 7638 del JWK enrolado),
  ``alg`` y ``nonce``;
- ``@target-uri`` se arma con ``PUBLIC_API_BASE_URL`` más la ruta y la query,
  no con la URL interna detrás del proxy de Render.

Pasos de la verificación (SRS §12.4): equipo por ``keyid``; ``|ahora - created|
<= 30 s`` (si no, ``MACHINE_CLOCK_SKEW``); nonce no visto en 60 s; digest del
cuerpo; base de firma y firma. Cualquier otro fallo responde
``MACHINE_SIGNATURE_INVALID``.
"""

import base64
import hashlib
import re
import threading
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import Request

from app.config import settings

ALGORITMO = "ecdsa-p256-sha256"
_ETIQUETA = r"[a-z][a-z0-9_-]*"
_PATRON_INPUT = re.compile(
    rf'^(?P<etiqueta>{_ETIQUETA})=(?P<params>\((?P<componentes>[^()]*)\)(?P<resto>(?:;[a-z]+=(?:"[^"]*"|\d+))*))$'
)
_PATRON_PARAM = re.compile(r';([a-z]+)=(?:"([^"]*)"|(\d+))')
_PATRON_FIRMA = re.compile(rf"^(?P<etiqueta>{_ETIQUETA})=:(?P<valor>[A-Za-z0-9+/=]+):$")
_PATRON_DIGEST = re.compile(r"(?:^|,)\s*sha-256=:([A-Za-z0-9+/=]+):")


class FirmaInvalida(Exception):
    """La petición no trae una firma válida (``MACHINE_SIGNATURE_INVALID``)."""


class RelojDesfasado(Exception):
    """``created`` está fuera de la tolerancia (``MACHINE_CLOCK_SKEW``)."""


@dataclass(frozen=True)
class EntradaFirma:
    """Datos de ``Signature-Input`` ya separados."""

    etiqueta: str
    componentes: tuple[str, ...]
    params_crudos: str
    created: int
    keyid: str
    alg: str
    nonce: str


class _NoncesVistos:
    """Memoria de nonces recientes por ``keyid`` para rechazar repeticiones."""

    def __init__(self) -> None:
        """Crea la memoria vacía."""
        self._vistos: dict[tuple[str, str], float] = {}
        self._candado = threading.Lock()

    def registrar(self, keyid: str, nonce: str, ahora: float | None = None) -> bool:
        """Guarda el nonce si es nuevo.

        Args:
            keyid: Huella de la clave del equipo.
            nonce: Nonce de la firma.
            ahora: Reloj monótono en segundos; solo para las pruebas.

        Returns:
            ``True`` si el nonce es nuevo; ``False`` si se repitió en la ventana.
        """
        ahora = time.monotonic() if ahora is None else ahora
        ventana = settings.firma_ventana_nonce_s
        with self._candado:
            for clave, momento in list(self._vistos.items()):
                if momento <= ahora - ventana:
                    del self._vistos[clave]
            if (keyid, nonce) in self._vistos:
                return False
            self._vistos[(keyid, nonce)] = ahora
            return True

    def reiniciar(self) -> None:
        """Olvida los nonces (pruebas)."""
        with self._candado:
            self._vistos.clear()


nonces = _NoncesVistos()


def trae_firma(request: Request) -> bool:
    """Indica si la petición trae las cabeceras de la firma.

    Args:
        request: Petición entrante.

    Returns:
        ``True`` si vienen ``Signature-Input`` y ``Signature``.
    """
    return "signature-input" in request.headers and "signature" in request.headers


def leer_entrada(valor: str) -> EntradaFirma:
    """Separa ``Signature-Input`` en sus componentes y parámetros.

    Args:
        valor: Cabecera ``Signature-Input`` (una sola firma).

    Returns:
        Los datos de la firma.

    Raises:
        FirmaInvalida: Si el formato no es el del perfil.
    """
    m = _PATRON_INPUT.fullmatch(valor.strip())
    if not m:
        raise FirmaInvalida("Signature-Input mal formado")
    componentes = tuple(re.findall(r'"([^"]+)"', m.group("componentes")))
    params: dict[str, str] = {}
    for nombre, texto, numero in _PATRON_PARAM.findall(m.group("resto")):
        if nombre in params:
            raise FirmaInvalida("parámetro repetido")
        params[nombre] = texto if texto or not numero else numero
    try:
        created = int(params["created"])
        keyid, alg, nonce = params["keyid"], params["alg"], params["nonce"]
    except (KeyError, ValueError):
        raise FirmaInvalida("faltan parámetros") from None
    if not keyid or not nonce:
        raise FirmaInvalida("keyid o nonce vacío")
    return EntradaFirma(m.group("etiqueta"), componentes, m.group("params"), created, keyid, alg, nonce)


def leer_firma(valor: str, etiqueta: str) -> bytes:
    """Decodifica la cabecera ``Signature`` de la etiqueta esperada.

    Args:
        valor: Cabecera ``Signature``.
        etiqueta: Etiqueta de ``Signature-Input`` (p. ej. ``sig1``).

    Returns:
        Los 64 bytes ``r||s``.

    Raises:
        FirmaInvalida: Si el formato, la etiqueta o el largo no son válidos.
    """
    m = _PATRON_FIRMA.fullmatch(valor.strip())
    if not m or m.group("etiqueta") != etiqueta:
        raise FirmaInvalida("Signature mal formada")
    try:
        crudo = base64.b64decode(m.group("valor"), validate=True)
    except ValueError:
        raise FirmaInvalida("Signature no es base64") from None
    if len(crudo) != 64:
        raise FirmaInvalida("la firma no mide 64 bytes")
    return crudo


def content_digest(cuerpo: bytes) -> str:
    """Calcula ``Content-Digest`` con SHA-256 (RFC 9530).

    Args:
        cuerpo: Bytes del cuerpo.

    Returns:
        ``sha-256=:<base64>:``.
    """
    return f"sha-256=:{base64.b64encode(hashlib.sha256(cuerpo).digest()).decode()}:"


def uri_firmada(request: Request) -> str:
    """Arma ``@target-uri`` con ``PUBLIC_API_BASE_URL`` (o la URL de la petición).

    Args:
        request: Petición entrante.

    Returns:
        URI absoluta: base pública, ruta y, si hay, query.
    """
    base = (settings.public_api_base_url or str(request.base_url)).rstrip("/")
    query = request.url.query
    return f"{base}{request.url.path}" + (f"?{query}" if query else "")


def base_de_firma(entrada: EntradaFirma, metodo: str, uri: str, digest: str | None) -> str:
    """Reconstruye la base de firma (RFC 9421 §2.5) igual que el firmador de referencia.

    Args:
        entrada: Datos de ``Signature-Input``.
        metodo: Método HTTP.
        uri: ``@target-uri``.
        digest: Valor de ``Content-Digest`` si es un componente.

    Returns:
        La base de firma, sin salto de línea final.

    Raises:
        FirmaInvalida: Si se pide un componente que no está en el perfil.
    """
    valores = {"@method": metodo.upper(), "@target-uri": uri, "content-digest": digest}
    lineas = []
    for componente in entrada.componentes:
        if componente not in valores or valores[componente] is None:
            raise FirmaInvalida(f"componente no soportado: {componente}")
        lineas.append(f'"{componente}": {valores[componente]}')
    lineas.append(f'"@signature-params": {entrada.params_crudos}')
    return "\n".join(lineas)


def verificar_r_s(jwk: dict, base: str, firma: bytes) -> bool:
    """Verifica una firma ``r||s`` ECDSA P-256 / SHA-256 con un JWK público.

    Args:
        jwk: Clave pública EC P-256 del equipo.
        base: Texto firmado.
        firma: 64 bytes ``r||s``.

    Returns:
        ``True`` si la firma es válida.
    """
    def coordenada(valor: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4)), "big")

    try:
        publica = ec.EllipticCurvePublicNumbers(
            coordenada(jwk["x"]), coordenada(jwk["y"]), ec.SECP256R1()
        ).public_key()
        der = encode_dss_signature(int.from_bytes(firma[:32], "big"), int.from_bytes(firma[32:], "big"))
        publica.verify(der, base.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, KeyError):
        return False
    return True


async def preparar(request: Request) -> tuple[EntradaFirma, bytes, str]:
    """Valida todo lo que no depende del equipo y arma la base de firma.

    Comprueba los componentes obligatorios, el algoritmo, el ``Content-Digest``
    del cuerpo y la ventana de reloj.

    Args:
        request: Petición entrante.

    Returns:
        Los datos de la firma, los 64 bytes de la firma y la base a verificar.

    Raises:
        FirmaInvalida: Si falta algo o no coincide.
        RelojDesfasado: Si ``created`` está fuera de la tolerancia.
    """
    entrada = leer_entrada(request.headers["signature-input"])
    firma = leer_firma(request.headers["signature"], entrada.etiqueta)
    if entrada.alg != ALGORITMO:
        raise FirmaInvalida("algoritmo no permitido")
    if not {"@method", "@target-uri"} <= set(entrada.componentes):
        raise FirmaInvalida("faltan componentes obligatorios")

    cuerpo = await request.body()
    digest = None
    if cuerpo or "content-digest" in entrada.componentes:
        if "content-digest" not in entrada.componentes:
            raise FirmaInvalida("el cuerpo no está cubierto por la firma")
        recibido = _PATRON_DIGEST.search(request.headers.get("content-digest", ""))
        digest = content_digest(cuerpo)
        if not recibido or f"sha-256=:{recibido.group(1)}:" != digest:
            raise FirmaInvalida("Content-Digest no coincide con el cuerpo")

    if abs(time.time() - entrada.created) > settings.firma_tolerancia_s:
        raise RelojDesfasado()

    base = base_de_firma(entrada, request.method, uri_firmada(request), digest)
    return entrada, firma, base
