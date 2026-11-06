"""Happy path tests for cryptographic hash, HMAC, and key ring helpers (SEC-00)."""

import hashlib
import hmac

from app.crypto import (
    compute_blind_index,
    constant_time_compare,
    hmac_sha256_digest,
    hmac_sha256_hex,
    parse_data_enc_keys,
    sha256_digest,
    sha256_hex,
)


def test_sha256_digest_happy_path():
    """Verify SHA-256 binary digest produces exact 32-byte hash."""
    test_data = "test-token-value-12345"
    expected = hashlib.sha256(test_data.encode("utf-8")).digest()

    result = sha256_digest(test_data)

    assert isinstance(result, bytes)
    assert len(result) == 32
    assert result == expected


def test_sha256_hex_happy_path():
    """Verify SHA-256 hex string matches expected 64-character lowercase hex."""
    test_data = "sample-identifier"
    expected = hashlib.sha256(test_data.encode("utf-8")).hexdigest()

    result = sha256_hex(test_data)

    assert isinstance(result, str)
    assert len(result) == 64
    assert result == expected


def test_hmac_sha256_digest_and_hex_happy_path():
    """Verify HMAC-SHA256 calculations for both raw bytes and hex representation."""
    test_key = bytes(range(32)).hex()
    payload = "machine-enrollment-challenge"
    key_bytes = bytes.fromhex(test_key)
    expected_digest = hmac.new(key_bytes, payload.encode("utf-8"), hashlib.sha256).digest()
    expected_hex = hmac.new(key_bytes, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    digest_result = hmac_sha256_digest(test_key, payload)
    hex_result = hmac_sha256_hex(test_key, payload)

    assert digest_result == expected_digest
    assert len(digest_result) == 32
    assert hex_result == expected_hex
    assert len(hex_result) == 64


def test_compute_blind_index_normalization_happy_path():
    """Verify blind index produces consistent hash with case and whitespace normalization."""
    test_key = bytes(range(32, 64)).hex()
    email_raw = "  User.Name@Example.EDU  "
    email_normalized = "user.name@example.edu"

    bidx_1 = compute_blind_index(email_raw, key=test_key)
    bidx_2 = compute_blind_index(email_normalized, key=test_key)

    assert isinstance(bidx_1, bytes)
    assert len(bidx_1) == 32
    assert bidx_1 == bidx_2


def test_constant_time_compare_happy_path():
    """Verify constant-time equality and inequality checks."""
    token_a = "secure-random-token-xyz"
    token_b = "secure-random-token-xyz"
    token_c = "different-random-token-xyz"

    assert constant_time_compare(token_a, token_b) is True
    assert constant_time_compare(token_a, token_c) is False


def test_parse_data_enc_keys_happy_path():
    """Verify parsing of valid JSON key ring with 32-byte encryption keys."""
    raw_json_ring = (
        '{"1": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",'
        ' "2": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"}'
    )

    parsed_ring = parse_data_enc_keys(raw_json_ring)

    assert "1" in parsed_ring
    assert "2" in parsed_ring
    assert len(parsed_ring["1"]) == 32
    assert len(parsed_ring["2"]) == 32
    assert parsed_ring["1"] == bytes.fromhex(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
