"""Cada código del catálogo tiene status y textos definidos (QA-03)."""

import pytest

from app.errors import CATALOGO, ErrorCode

CODIGOS_SRS = {
    "VALIDATION_ERROR": 422,
    "AUTH_INVALID_CREDENTIALS": 401,
    "AUTH_EMAIL_NOT_VERIFIED": 403,
    "AUTH_ACCOUNT_LOCKED": 423,
    "AUTH_TOKEN_EXPIRED": 401,
    "FORBIDDEN": 403,
    "RATE_LIMITED": 429,
    "CHALLENGE_NOT_FOUND": 404,
    "CHALLENGE_EXPIRED": 410,
    "CHALLENGE_ALREADY_USED": 409,
    "MACHINE_BUSY": 409,
    "MACHINE_DISABLED": 403,
    "MACHINE_SIGNATURE_INVALID": 401,
    "MACHINE_CLOCK_SKEW": 401,
    "ENROLLMENT_CODE_INVALID": 401,
    "SESSION_NOT_FOUND": 404,
}


def test_no_hay_codigos_huerfanos() -> None:
    assert set(CATALOGO) == set(ErrorCode)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_cada_codigo_tiene_status_y_textos(code: ErrorCode) -> None:
    assert 400 <= code.spec.status < 600
    assert code.spec.title.strip()
    assert code.spec.detail.strip()


def test_status_coinciden_con_srs() -> None:
    for nombre, status in CODIGOS_SRS.items():
        assert ErrorCode[nombre].spec.status == status, nombre


def test_type_uri_en_kebab() -> None:
    assert ErrorCode.MACHINE_CLOCK_SKEW.type_uri.endswith("/machine-clock-skew")
