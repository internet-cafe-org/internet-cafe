"""Firma de peticiones del equipo para las pruebas (RFC 9421, perfil de SEC-08)."""

import base64
import secrets
import time
from collections.abc import Generator
from functools import lru_cache

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.config import settings
from app.security import firma
from app.services.enrolamiento import huella_jwk


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

    @property
    def clave_enrolada(self) -> dict:
        """Columnas de ``Machine`` que deja el enrolamiento con esta clave."""
        return {"public_key_jwk": self.jwk, "key_thumbprint": self.keyid}


@lru_cache
def firmador_de(codigo: str) -> Firmador:
    """Devuelve siempre el mismo par de claves para un código de equipo.

    Args:
        codigo: Código del equipo.

    Returns:
        El firmador de ese equipo.
    """
    return Firmador()


class FirmaEquipo(httpx.Auth):
    """Autenticación de httpx que firma cada petición como el escritorio."""

    requires_request_body = True

    def __init__(self, firmador: Firmador) -> None:
        """Guarda el firmador del equipo."""
        self.firmador = firmador

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Agrega las cabeceras de la firma, con un nonce nuevo por petición."""
        uri = str(request.url)
        if settings.public_api_base_url:
            uri = settings.public_api_base_url.rstrip("/") + request.url.raw_path.decode()
        request.headers.update(self.firmador.cabeceras(request.method, uri, request.content))
        yield request


def firma_de(codigo: str) -> FirmaEquipo:
    """Autenticación de httpx para el equipo con ese código.

    Args:
        codigo: Código del equipo.

    Returns:
        El objeto que se pasa como ``auth=`` a httpx.
    """
    return FirmaEquipo(firmador_de(codigo))
