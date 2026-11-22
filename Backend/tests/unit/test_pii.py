"""SEC-06: cifrado AES-256-GCM de la interfaz pii."""

import json

import pytest

from app.config import settings
from app.services import pii

LLAVE_1 = "00" * 32
LLAVE_2 = "11" * 32


@pytest.fixture(autouse=True)
def anillo(monkeypatch):
    monkeypatch.setattr(settings, "data_enc_keys", json.dumps({"1": LLAVE_1}))


def test_cifra_y_descifra():
    dato = pii.proteger("ana@u.edu", aad="users.email_ct.abc")
    assert dato.startswith(b"v1|")
    assert b"ana@u.edu" not in dato
    assert pii.revelar(dato, aad="users.email_ct.abc") == "ana@u.edu"


def test_unicode():
    dato = pii.proteger("José Núñez ñ", aad="users.full_name_ct.1")
    assert pii.revelar(dato, aad="users.full_name_ct.1") == "José Núñez ñ"


def test_nonce_distinto_cada_vez():
    assert pii.proteger("x", aad="t.c.1") != pii.proteger("x", aad="t.c.1")


def test_aad_distinto_falla():
    dato = pii.proteger("ana@u.edu", aad="users.email_ct.1")
    with pytest.raises(pii.PiiError):
        pii.revelar(dato, aad="users.email_ct.2")


def test_dato_alterado_falla():
    dato = bytearray(pii.proteger("ana@u.edu", aad="t.c.1"))
    dato[-1] ^= 1
    with pytest.raises(pii.PiiError):
        pii.revelar(bytes(dato), aad="t.c.1")


def test_sin_aad_no_descifra():
    dato = pii.proteger("ana@u.edu", aad="t.c.1")
    with pytest.raises(pii.PiiError):
        pii.revelar(dato)


def test_rotacion_de_llaves(monkeypatch):
    viejo = pii.proteger("ana@u.edu", aad="t.c.1")
    monkeypatch.setattr(
        settings, "data_enc_keys", json.dumps({"1": LLAVE_1, "2": LLAVE_2, "current": "2"})
    )
    assert pii.proteger("x", aad="t.c.1").startswith(b"v2|")
    assert pii.revelar(viejo, aad="t.c.1") == "ana@u.edu"


def test_compatibilidad_con_datos_en_claro():
    assert pii.revelar(b"ana@u.edu") == "ana@u.edu"
    assert pii.revelar(None, "vacio") == "vacio"
    assert pii.proteger("hola") == b"hola"
