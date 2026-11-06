"""Hash de contraseñas con Argon2id y política de largo."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

# Parámetros mínimos recomendados por OWASP: 19 MiB de memoria, 2 iteraciones, 1 hilo.
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    type=Type.ID,
)


class PasswordPolicyError(ValueError):
    """La contraseña no cumple la política de largo."""


def validate_password_policy(password: str) -> None:
    """Exige entre 10 y 128 caracteres. No recorta ni exige símbolos."""
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(
            f"La contraseña debe tener entre {PASSWORD_MIN_LENGTH} "
            f"y {PASSWORD_MAX_LENGTH} caracteres."
        )


def hash_password(password: str) -> str:
    """Valida la política y devuelve el hash Argon2id ($argon2id$...)."""
    validate_password_policy(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True si la contraseña coincide con el hash guardado."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False