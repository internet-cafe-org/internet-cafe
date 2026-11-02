"""Cryptographic utility functions for hashing, HMAC, and blind indexing.

Provides deterministic and one-way operations used across the system (SEC-00),
including SHA-256 digests, HMAC-SHA256 blind indexing, constant-time comparisons,
and versioned key ring utilities for DATA_ENC_KEYS.
"""

import hashlib
import hmac
import json
from typing import Mapping

from app.config import settings


def to_bytes(data: str | bytes) -> bytes:
    """Convert string or bytes input to bytes using UTF-8 encoding.

    Args:
        data: Input string or bytes.

    Returns:
        Encoded bytes.
    """
    if isinstance(data, bytes):
        return data
    return data.encode("utf-8")


def sha256_digest(data: str | bytes) -> bytes:
    """Compute the raw 32-byte SHA-256 digest of input data.

    Used for single-direction hashes such as opaque token hashes and code hashes.

    Args:
        data: String or bytes to hash.

    Returns:
        32-byte raw binary digest.
    """
    return hashlib.sha256(to_bytes(data)).digest()


def sha256_hex(data: str | bytes) -> str:
    """Compute the hexadecimal SHA-256 digest of input data.

    Args:
        data: String or bytes to hash.

    Returns:
        64-character hexadecimal digest string.
    """
    return hashlib.sha256(to_bytes(data)).hexdigest()


def hmac_sha256_digest(key: str | bytes, data: str | bytes) -> bytes:
    """Compute raw 32-byte HMAC-SHA256 message authentication code.

    Args:
        key: Secret HMAC key (string or bytes). If key is a 64-char hex string,
             it is parsed into raw bytes; otherwise UTF-8 encoded.
        data: Message payload to authenticate.

    Returns:
        32-byte raw binary HMAC digest.
    """
    key_bytes = _normalize_key(key)
    return hmac.new(key_bytes, to_bytes(data), hashlib.sha256).digest()


def hmac_sha256_hex(key: str | bytes, data: str | bytes) -> str:
    """Compute hexadecimal HMAC-SHA256 message authentication code.

    Args:
        key: Secret HMAC key (string or bytes).
        data: Message payload to authenticate.

    Returns:
        64-character hexadecimal HMAC string.
    """
    key_bytes = _normalize_key(key)
    return hmac.new(key_bytes, to_bytes(data), hashlib.sha256).hexdigest()


def compute_blind_index(value: str, key: str | bytes | None = None) -> bytes:
    """Compute deterministic blind index HMAC-SHA256 for exact database lookups.

    Values are normalized (trimmed and lowercased) before hashing to ensure
    consistent matching for searchable fields like email and student code.

    Args:
        value: String value to index (e.g., email address or student code).
        key: Optional secret key. If not provided, settings.blind_index_key is used.

    Returns:
        32-byte binary blind index suitable for *_bidx database columns.

    Raises:
        ValueError: If key is not provided and settings.blind_index_key is empty.
    """
    active_key = key or settings.blind_index_key
    if not active_key:
        raise ValueError("Blind index key must be provided or configured in settings.")

    normalized = value.strip().lower()
    return hmac_sha256_digest(active_key, normalized)


def constant_time_compare(val1: str | bytes, val2: str | bytes) -> bool:
    """Compare two values in constant time to prevent timing attacks.

    Args:
        val1: First value (string or bytes).
        val2: Second value (string or bytes).

    Returns:
        True if values are equal, False otherwise.
    """
    b1 = to_bytes(val1)
    b2 = to_bytes(val2)
    return hmac.compare_digest(b1, b2)


def parse_data_enc_keys(raw_ring: str | Mapping[str, str]) -> dict[str, bytes]:
    """Parse a versioned encryption key ring (DATA_ENC_KEYS).

    Expects a JSON string or mapping of version IDs to key strings
    (either 64-character hex strings or raw keys).

    Args:
        raw_ring: JSON string or dictionary mapping version -> key.

    Returns:
        Dictionary mapping version string (e.g., '1', '2') to 32-byte binary key.

    Raises:
        ValueError: If key ring format is invalid or key length is not 32 bytes (256 bits).
    """
    if isinstance(raw_ring, str):
        try:
            ring_data = json.loads(raw_ring)
        except json.JSONDecodeError as exc:
            raise ValueError("DATA_ENC_KEYS must be valid JSON.") from exc
    elif isinstance(raw_ring, Mapping):
        ring_data = dict(raw_ring)
    else:
        raise ValueError("DATA_ENC_KEYS must be a JSON string or mapping.")

    parsed: dict[str, bytes] = {}
    for version, key_repr in ring_data.items():
        if version == "current":
            continue
        parsed_key = _normalize_key(key_repr)
        if len(parsed_key) != 32:
            raise ValueError(
                f"Key for version {version} must be exactly 32 bytes (256 bits), got {len(parsed_key)}."
            )
        parsed[str(version)] = parsed_key

    if not parsed:
        raise ValueError("Key ring must contain at least one encryption key version.")

    return parsed


def _normalize_key(key: str | bytes) -> bytes:
    """Normalize a secret key representation into raw bytes.

    If the string is 64 hex characters (32 bytes encoded as hex), it is decoded.
    Otherwise UTF-8 bytes are returned.
    """
    if isinstance(key, bytes):
        return key
    key_str = key.strip()
    if len(key_str) == 64:
        try:
            return bytes.fromhex(key_str)
        except ValueError:
            pass
    return key_str.encode("utf-8")
