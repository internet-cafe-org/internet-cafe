"""Interfaz `pii`: único punto de entrada a los datos personales cifrados (SEC-06).

Cifrado AES-256-GCM con el anillo DATA_ENC_KEYS. Formato guardado:
    b"v{id_llave}|" + nonce (12 bytes) + b"|" + ciphertext (incluye la etiqueta GCM)
El AAD (tabla.columna.id) liga el texto cifrado a su fila: moverlo a otra fila falla.
"""

import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.crypto import compute_blind_index, parse_data_enc_keys

NONCE_LEN = 12


class PiiError(Exception):
    """El dato no se pudo cifrar o descifrar."""


def _anillo() -> tuple[dict[str, bytes], str]:
    """Devuelve (llaves por versión, versión actual)."""
    bruto = settings.data_enc_keys
    if not bruto:
        raise PiiError("DATA_ENC_KEYS no está configurada.")
    llaves = parse_data_enc_keys(bruto)
    actual = None
    try:
        actual = json.loads(bruto).get("current")
    except (ValueError, AttributeError):
        pass
    if actual is None:
        actual = max(llaves, key=lambda v: int(v) if v.isdigit() else -1)
    if str(actual) not in llaves:
        raise PiiError("La versión actual no está en DATA_ENC_KEYS.")
    return llaves, str(actual)


def _es_cifrado(dato: bytes) -> bool:
    if not dato.startswith(b"v"):
        return False
    corte = dato.find(b"|")
    return corte > 1 and dato[1:corte].isdigit()


def proteger(valor: str, aad: str | None = None) -> bytes:
    """Prepara un dato personal para una columna ``*_ct``.

    Sin ``aad`` se guarda sin cifrar (compatibilidad con quienes aún no migran).
    """
    if aad is None:
        return valor.encode("utf-8")
    llaves, version = _anillo()
    nonce = os.urandom(NONCE_LEN)
    cifrado = AESGCM(llaves[version]).encrypt(nonce, valor.encode("utf-8"), aad.encode("utf-8"))
    return b"v" + version.encode() + b"|" + nonce + b"|" + cifrado


def revelar(dato: bytes | None, defecto: str = "", aad: str | None = None) -> str:
    """Recupera el texto de una columna ``*_ct``.

    Los datos antiguos sin cifrar se devuelven tal cual. Los cifrados exigen ``aad``.
    """
    if not dato:
        return defecto
    if not _es_cifrado(dato):
        return dato.decode("utf-8", errors="replace")
    if aad is None:
        raise PiiError("Falta el aad para descifrar.")
    corte = dato.find(b"|")
    version = dato[1:corte].decode()
    nonce = dato[corte + 1 : corte + 1 + NONCE_LEN]
    ct = dato[corte + 2 + NONCE_LEN :]
    llaves, _ = _anillo()
    if version not in llaves or len(nonce) != NONCE_LEN:
        raise PiiError("Dato cifrado inválido.")
    try:
        return AESGCM(llaves[version]).decrypt(nonce, ct, aad.encode("utf-8")).decode("utf-8")
    except InvalidTag as exc:
        raise PiiError("El dato fue alterado o no corresponde a esta fila.") from exc


def indice_ciego(valor: str) -> bytes:
    """HMAC-SHA256 del valor normalizado con ``BLIND_INDEX_KEY``."""
    return compute_blind_index(valor)
