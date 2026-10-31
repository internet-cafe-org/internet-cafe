"""Pruebas de hash Argon2id y política de contraseñas."""

import pytest

from app.services.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PasswordPolicyError,
    hash_password,
    verify_password,
)

VALID_PASSWORD = "una-clave-larga-123"


def test_hash_uses_argon2id_and_verifies():
    password_hash = hash_password(VALID_PASSWORD)

    assert password_hash.startswith("$argon2id$")
    assert password_hash != VALID_PASSWORD
    assert verify_password(VALID_PASSWORD, password_hash) is True


def test_wrong_password_does_not_verify():
    password_hash = hash_password(VALID_PASSWORD)

    assert verify_password("otra-clave-distinta", password_hash) is False


def test_same_password_produces_different_hashes():
    assert hash_password(VALID_PASSWORD) != hash_password(VALID_PASSWORD)


@pytest.mark.parametrize("length", [PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH])
def test_accepts_boundary_lengths(length):
    assert hash_password("a" * length).startswith("$argon2id$")


@pytest.mark.parametrize("length", [PASSWORD_MIN_LENGTH - 1, PASSWORD_MAX_LENGTH + 1])
def test_rejects_out_of_range_lengths(length):
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * length)