"""JSON Web Token (JWT) issuance and verification module (SEC-00).

Strictly enforces ECDSA using SHA-256 (ES256) with a fixed algorithm constant.
The algorithm is hardcoded and NEVER read from the token header or payload to
prevent algorithm confusion and downgrade attacks (e.g., 'none' or HMAC confusion).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import jwt
from app.config import settings

# Enforce ES256 as a fixed constant across this module.
# The algorithm is NEVER dynamically extracted from incoming tokens.
ALGORITHM: str = "ES256"


class JWTError(Exception):
    """Base exception for JWT processing errors."""


class TokenExpiredError(JWTError):
    """Raised when a token has expired."""


class InvalidTokenError(JWTError):
    """Raised when a token signature or claims validation fails."""


def _load_key_content(key_or_path: str | bytes | None) -> str:
    """Load PEM key content from a string or file path.

    Args:
        key_or_path: PEM string, bytes, or file path to a PEM file.

    Returns:
        PEM formatted string content.

    Raises:
        ValueError: If key is not provided or file cannot be read.
    """
    if not key_or_path:
        raise ValueError("Key content or file path must be provided.")

    if isinstance(key_or_path, bytes):
        return key_or_path.decode("utf-8")

    key_str = key_or_path.strip()
    if "-----BEGIN" in key_str:
        return key_str

    if os.path.exists(key_str):
        with open(key_str, "r", encoding="utf-8") as f:
            return f.read().strip()

    raise ValueError("Invalid key: neither a PEM-formatted string nor an existing file path.")


def create_access_token(
    subject: str,
    role: str,
    private_key: str | bytes | None = None,
    expires_delta: timedelta | None = None,
    extra_claims: Mapping[str, Any] | None = None,
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Issue a signed ES256 access token with standard claims.

    Claims populated:
      - iss: Token issuer (default: settings.jwt_issuer or 'internet-cafe-api')
      - aud: Target audience (default: settings.jwt_audience or 'web')
      - sub: Subject identifier (user UUID / identifier)
      - role: User role (e.g. 'student', 'admin')
      - jti: Unique identifier for the token (UUID4)
      - iat: Issued at timestamp (UTC)
      - exp: Expiration timestamp (UTC, default 10 minutes)

    Args:
        subject: Subject identifier (e.g., user id).
        role: User role name.
        private_key: ES256 PEM private key or path. If None, uses settings.jwt_private_key.
        expires_delta: Optional custom lifetime timedelta.
        extra_claims: Optional extra claims to include in the payload.
        issuer: Optional custom issuer string.
        audience: Optional custom audience string.

    Returns:
        Encoded and signed JWT string.

    Raises:
        ValueError: If subject or private key is missing.
    """
    if not subject:
        raise ValueError("Subject claim (sub) cannot be empty.")

    key_source = private_key or settings.jwt_private_key
    if not key_source:
        raise ValueError("JWT private key must be configured in settings or passed explicitly.")

    pem_private_key = _load_key_content(key_source)
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire_time = now + expires_delta
    else:
        minutes = getattr(settings, "jwt_access_token_expire_minutes", 10) or 10
        expire_time = now + timedelta(minutes=minutes)

    iss = issuer or getattr(settings, "jwt_issuer", "internet-cafe-api")
    aud = audience or getattr(settings, "jwt_audience", "web")

    payload: dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "sub": str(subject),
        "role": str(role),
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire_time.timestamp()),
    }

    if extra_claims:
        for k, v in extra_claims.items():
            if k not in payload:
                payload[k] = v

    token = jwt.encode(payload, pem_private_key, algorithm=ALGORITHM)
    return token


def verify_access_token(
    token: str,
    public_key: str | bytes | None = None,
    issuer: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    """Verify and decode an ES256 access token with fixed algorithm enforcement.

    CRITICAL SECURITY GUARANTEE:
    The algorithm is strictly enforced as [ALGORITHM] ('ES256') in python code.
    Any token with 'none', symmetric HMAC, or non-ES256 algorithm will fail verification.

    Args:
        token: JWT string to verify.
        public_key: ES256 PEM public key or path. If None, uses settings.jwt_public_key.
        issuer: Expected token issuer (default: settings.jwt_issuer).
        audience: Expected audience (default: settings.jwt_audience).

    Returns:
        Decoded claims dictionary.

    Raises:
        TokenExpiredError: If token has expired.
        InvalidTokenError: If signature, algorithm, audience, issuer, or format is invalid.
    """
    key_source = public_key or settings.jwt_public_key
    if not key_source:
        raise ValueError("JWT public key must be configured in settings or passed explicitly.")

    pem_public_key = _load_key_content(key_source)

    expected_iss = issuer or getattr(settings, "jwt_issuer", "internet-cafe-api")
    expected_aud = audience or getattr(settings, "jwt_audience", "web")

    try:
        # Pre-check header to ensure algorithm matches ALGORITHM before decoding
        unverified_header = jwt.get_unverified_header(token)
        if unverified_header.get("alg") != ALGORITHM:
            raise InvalidTokenError(
                f"Disallowed token algorithm. Expected fixed '{ALGORITHM}', "
                f"got '{unverified_header.get('alg')}'."
            )

        payload = jwt.decode(
            token,
            pem_public_key,
            algorithms=[ALGORITHM],  # Hardcoded list: never read from token
            issuer=expected_iss,
            audience=expected_aud,
            options={
                "require": ["exp", "iat", "sub", "role", "jti", "iss", "aud"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"Invalid token: {exc}") from exc
    except Exception as exc:
        raise InvalidTokenError(f"Token verification failed: {exc}") from exc
