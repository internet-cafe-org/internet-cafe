"""ST-SEC-01: logica pura del OTP."""

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.services import otp


@pytest.fixture(autouse=True)
def _clave(monkeypatch):
    monkeypatch.setattr(settings, "otp_hmac_key", secrets.token_hex(32))


def test_codigo_tiene_seis_digitos():
    for _ in range(200):
        assert re.fullmatch(r"\d{6}", otp.generar_codigo())


def test_codigo_correcto_y_vigente():
    uid, ahora = uuid.uuid4(), datetime.now(UTC)
    h = otp.hash_codigo("123456", uid, "verify_email")
    assert otp.verificar("123456", uid, "verify_email", h, 0, otp.vence_en(ahora), ahora)


def test_codigo_incorrecto():
    uid, ahora = uuid.uuid4(), datetime.now(UTC)
    h = otp.hash_codigo("123456", uid, "verify_email")
    assert not otp.verificar("654321", uid, "verify_email", h, 0, otp.vence_en(ahora), ahora)


def test_vencido_a_los_10_minutos():
    uid, ahora = uuid.uuid4(), datetime.now(UTC)
    h = otp.hash_codigo("123456", uid, "verify_email")
    exp = otp.vence_en(ahora)
    assert otp.verificar("123456", uid, "verify_email", h, 0, exp, exp - timedelta(seconds=1))
    assert not otp.verificar("123456", uid, "verify_email", h, 0, exp, exp)


def test_cinco_intentos_lo_invalidan():
    uid, ahora = uuid.uuid4(), datetime.now(UTC)
    h = otp.hash_codigo("123456", uid, "verify_email")
    assert not otp.verificar("123456", uid, "verify_email", h, 5, otp.vence_en(ahora), ahora)


def test_no_sirve_para_otro_proposito_ni_usuario():
    uid, ahora = uuid.uuid4(), datetime.now(UTC)
    h = otp.hash_codigo("123456", uid, "verify_email")
    exp = otp.vence_en(ahora)
    assert not otp.verificar("123456", uid, "reset_password", h, 0, exp, ahora)
    assert not otp.verificar("123456", uuid.uuid4(), "verify_email", h, 0, exp, ahora)


def test_sin_clave_falla(monkeypatch):
    monkeypatch.setattr(settings, "otp_hmac_key", None)
    with pytest.raises(ValueError):
        otp.hash_codigo("123456", uuid.uuid4(), "verify_email")