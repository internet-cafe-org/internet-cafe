"""Pruebas de los vectores y del firmador de referencia (SEC-08)."""

import copy
import json
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parents[3] / "contracts" / "test-vectors"
sys.path.insert(0, str(CARPETA))

import firmador_referencia as fr  # noqa: E402
import generar_vectores  # noqa: E402

V = json.loads((CARPETA / "vectores.json").read_text(encoding="utf-8"))
CLAVES = V["claves_solo_de_prueba"]


def _caso(nombre):
    return next(c for c in V["casos"] if c["nombre"] == nombre)


def _peticion(c):
    p = c["peticion"]
    cuerpo = p["cuerpo_utf8"].encode() if p["cuerpo_utf8"] is not None else None
    return fr.Peticion(p["metodo"], p["base_publica"] + p["ruta"], cuerpo)


def _sin_firma(d):
    d = copy.deepcopy(d)
    for c in d["casos"]:
        c.pop("firma_de_ejemplo")
    return d


def test_vectores_json_esta_al_dia():
    assert _sin_firma(generar_vectores.construir()) == _sin_firma(V)


def test_digest_de_referencia_rfc_9530():
    assert fr.content_digest(b'{"hello": "world"}') == "sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:"
    assert fr.content_digest(b"") == "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:"


def test_base_de_firma_y_digest_se_recalculan():
    for c in V["casos"]:
        p, e = _peticion(c), c["esperado"]
        base, params = fr.base_de_firma(p, c["parametros"]["created"], e["keyid"], c["parametros"]["nonce"])
        assert base == e["base_de_firma"], c["nombre"]
        assert f"{fr.ETIQUETA}={params}" == e["signature_input"], c["nombre"]
        assert f'"@target-uri": {p.uri}' in base, c["nombre"]
        if p.cuerpo:
            assert fr.content_digest(p.cuerpo) == e["content_digest"], c["nombre"]


def test_digest_unicode_usa_bytes_utf8():
    c = _caso("post_con_cuerpo_unicode")
    texto = c["peticion"]["cuerpo_utf8"]
    assert len(texto.encode()) > len(texto)
    assert c["esperado"]["content_digest"] == fr.content_digest(texto.encode())


def test_get_sin_cuerpo_no_firma_content_digest():
    e = _caso("get_sin_cuerpo")["esperado"]
    assert e["content_digest"] is None
    assert e["componentes"] == ["@method", "@target-uri"]
    assert "content-digest" not in e["base_de_firma"]
    assert "?wait=25" in e["base_de_firma"]


def test_firmas_de_ejemplo_se_verifican():
    for c in V["casos"]:
        publica = fr.publica_desde_jwk(CLAVES[c["clave"]]["jwk_publica"])
        firma = fr.base64.b64decode(c["firma_de_ejemplo"])
        assert fr.verificar_base(publica, c["esperado"]["base_de_firma"], firma), c["nombre"]


def test_firma_alterada_no_se_verifica():
    c = _caso("post_con_cuerpo_json")
    publica = fr.publica_desde_jwk(CLAVES["normal"]["jwk_publica"])
    firma = fr.base64.b64decode(c["firma_de_ejemplo"])
    base = c["esperado"]["base_de_firma"]
    assert not fr.verificar_base(publica, base.replace("POST", "GET "), firma)
    assert not fr.verificar_base(publica, base, bytes([firma[0] ^ 1]) + firma[1:])


def test_clave_con_cero_inicial_conserva_32_bytes():
    k = CLAVES["cero_inicial"]
    jwk = k["jwk_publica"]
    x, y = fr.b64url_dec(jwk["x"]), fr.b64url_dec(jwk["y"])
    assert len(jwk["x"]) == 43 and len(jwk["y"]) == 43 and len(x) == 32 and len(y) == 32
    assert x[0] == 0 or y[0] == 0
    assert fr.huella_rfc7638(jwk) == k["huella_rfc7638"]
    recortada = {**jwk, "x": fr.b64url(x.lstrip(b"\x00")), "y": fr.b64url(y.lstrip(b"\x00"))}
    assert fr.huella_rfc7638(recortada) != k["huella_rfc7638"]


def test_la_clave_normal_no_empieza_con_cero():
    jwk = CLAVES["normal"]["jwk_publica"]
    assert fr.b64url_dec(jwk["x"])[0] != 0 and fr.b64url_dec(jwk["y"])[0] != 0