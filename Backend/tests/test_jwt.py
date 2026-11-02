"""Happy path tests for ES256 JWT issuance and verification (SEC-00)."""

from datetime import timedelta
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.jwt import (
    ALGORITHM,
    InvalidTokenError,
    create_access_token,
    verify_access_token,
)


@pytest.fixture(scope="session")
def es256_keypair() -> tuple[str, str]:
    """Generate ephemeral ES256 keypair for testing suite."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def test_create_and_verify_access_token_happy_path(es256_keypair):
    """Verify standard access token issuance and verification with required claims."""
    private_pem, public_pem = es256_keypair
    subject_id = "00000000-0000-0000-0000-000000000001"
    user_role = "student"

    token = create_access_token(
        subject=subject_id,
        role=user_role,
        private_key=private_pem,
    )

    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    claims = verify_access_token(token, public_key=public_pem)

    assert claims["sub"] == subject_id
    assert claims["role"] == user_role
    assert claims["aud"] == "web"
    assert claims["iss"] == "internet-cafe-api"
    assert "jti" in claims
    assert "iat" in claims
    assert "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_jwt_fixed_algorithm_enforcement(es256_keypair):
    """Verify the module strictly enforces fixed ES256 algorithm."""
    private_pem, public_pem = es256_keypair

    assert ALGORITHM == "ES256"

    token = create_access_token(
        subject="admin-user-01",
        role="admin",
        private_key=private_pem,
    )

    claims = verify_access_token(token, public_key=public_pem)
    assert claims["role"] == "admin"


def test_jwt_with_custom_expiration_and_extra_claims(es256_keypair):
    """Verify custom delta and extra claims in JWT payload."""
    private_pem, public_pem = es256_keypair
    delta = timedelta(minutes=15)
    extra = {"session_type": "provisional", "client_ip": "127.0.0.1"}

    token = create_access_token(
        subject="student-user-42",
        role="student",
        private_key=private_pem,
        expires_delta=delta,
        extra_claims=extra,
    )

    claims = verify_access_token(token, public_key=public_pem)
    assert claims["session_type"] == "provisional"
    assert claims["client_ip"] == "127.0.0.1"
    assert (claims["exp"] - claims["iat"]) == 15 * 60


def test_jwt_key_loading_from_file_path(tmp_path, es256_keypair):
    """Verify PEM key loading directly from filesystem paths."""
    private_pem, public_pem = es256_keypair
    priv_file = tmp_path / "test_private.pem"
    pub_file = tmp_path / "test_public.pem"

    priv_file.write_text(private_pem, encoding="utf-8")
    pub_file.write_text(public_pem, encoding="utf-8")

    token = create_access_token(
        subject="user-from-file-key",
        role="student",
        private_key=str(priv_file),
    )

    claims = verify_access_token(token, public_key=str(pub_file))
    assert claims["sub"] == "user-from-file-key"
