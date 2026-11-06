"""Firmador de referencia RFC 9421 + RFC 9530 (SEC-08). Fuente de verdad de los vectores."""

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

# PERFIL del proyecto: si el SRS define otra cosa, se cambia aqui y se regeneran los vectores.
ETIQUETA = "sig1"
ALGORITMO = "ecdsa-p256-sha256"
ORDEN = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def b64(d: bytes) -> str:
    return base64.b64encode(d).decode()


def b64url(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def b64url_dec(t: str) -> bytes:
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def clave_determinista(etiqueta: str, cero_inicial: bool = False):
    """Clave P-256 reproducible (solo pruebas). Con cero_inicial, x o y empieza en 0x00."""
    i = 0
    while True:
        semilla = hashlib.sha256(f"{etiqueta}:{i}".encode()).digest()
        clave = ec.derive_private_key(int.from_bytes(semilla, "big") % (ORDEN - 1) + 1, ec.SECP256R1())
        n = clave.public_key().public_numbers()
        if ((n.x >> 248) == 0 or (n.y >> 248) == 0) == cero_inicial:
            return clave
        i += 1


def jwk_publica(clave) -> dict:
    """JWK publica con coordenadas SIEMPRE de 32 bytes (RFC 7518)."""
    n = clave.public_key().public_numbers() if hasattr(clave, "public_key") else clave.public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": b64url(n.x.to_bytes(32, "big")), "y": b64url(n.y.to_bytes(32, "big"))}


def jwk_privada(clave) -> dict:
    return {**jwk_publica(clave), "d": b64url(clave.private_numbers().private_value.to_bytes(32, "big"))}


def publica_desde_jwk(jwk: dict):
    x, y = int.from_bytes(b64url_dec(jwk["x"]), "big"), int.from_bytes(b64url_dec(jwk["y"]), "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def huella_rfc7638(jwk: dict) -> str:
    """Huella JWK (RFC 7638): SHA-256 del JSON canonico, en base64url."""
    canonico = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(canonico.encode()).digest())


def content_digest(cuerpo: bytes) -> str:
    return f"sha-256=:{b64(hashlib.sha256(cuerpo).digest())}:"


@dataclass(frozen=True)
class Peticion:
    metodo: str
    uri: str  # absoluta, armada desde PUBLIC_API_BASE_URL
    cuerpo: bytes | None = None


def componentes(p: Peticion) -> list[str]:
    return ["@method", "@target-uri"] + (["content-digest"] if p.cuerpo else [])


def base_de_firma(p: Peticion, created: int, keyid: str, nonce: str) -> tuple[str, str]:
    """Devuelve (base de firma, @signature-params). La base no termina en salto de linea."""
    valores = {"@method": p.metodo.upper(), "@target-uri": p.uri}
    if p.cuerpo:
        valores["content-digest"] = content_digest(p.cuerpo)
    lista = " ".join(f'"{c}"' for c in componentes(p))
    params = f'({lista});created={created};keyid="{keyid}";alg="{ALGORITMO}";nonce="{nonce}"'
    lineas = [f'"{c}": {valores[c]}' for c in componentes(p)] + [f'"@signature-params": {params}']
    return "\n".join(lineas), params


def firmar_base(clave, base: str) -> bytes:
    """ECDSA P-256/SHA-256 como r||s de 64 bytes (RFC 9421 3.3.4)."""
    r, s = decode_dss_signature(clave.sign(base.encode(), ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verificar_base(publica, base: str, firma: bytes) -> bool:
    if len(firma) != 64:
        return False
    der = encode_dss_signature(int.from_bytes(firma[:32], "big"), int.from_bytes(firma[32:], "big"))
    try:
        publica.verify(der, base.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


def firmar_peticion(clave, p: Peticion, created: int, nonce: str) -> dict:
    keyid = huella_rfc7638(jwk_publica(clave))
    base, params = base_de_firma(p, created, keyid, nonce)
    return {"base": base, "signature_input": f"{ETIQUETA}={params}", "keyid": keyid, "firma": b64(firmar_base(clave, base))}