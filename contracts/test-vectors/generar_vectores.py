"""Genera vectores.json (SEC-08). Uso, desde la raiz del repo:
    python contracts/test-vectors/generar_vectores.py

Claves, created y nonce son constantes: base, digest y claves salen iguales siempre.
La firma ECDSA lleva un valor aleatorio, por eso las pruebas la VERIFICAN, no la comparan.
Las claves son SOLO de prueba.
"""

import json
from pathlib import Path

import firmador_referencia as fr

BASE_PUBLICA = "https://api.internet-cafe.example"  # valor de PUBLIC_API_BASE_URL
CREATED, NONCE = 1793750000, "dGVzdC1ub25jZS0wMDAx"
CLAVES = {
    "normal": fr.clave_determinista("internet-cafe vector normal"),
    "cero_inicial": fr.clave_determinista("internet-cafe vector cero inicial", cero_inicial=True),
}
CASOS = [
    ("post_con_cuerpo_json", "normal", "POST", "/api/v1/machine/challenges", '{"machine_code":"LAB-01-PC01"}'),
    ("post_con_cuerpo_unicode", "normal", "POST", "/api/v1/machine/events", '{"nota":"sesi\u00f3n \u00f1and\u00fa \u2713"}'),
    ("get_sin_cuerpo", "normal", "GET", "/api/v1/machine/challenges/current?wait=25", None),
    ("clave_con_cero_inicial", "cero_inicial", "POST", "/api/v1/machine/challenges", '{"machine_code":"LAB-01-PC02"}'),
]


def construir() -> dict:
    claves = {}
    for nombre, k in CLAVES.items():
        pub = fr.jwk_publica(k)
        claves[nombre] = {"jwk_privada": fr.jwk_privada(k), "jwk_publica": pub, "huella_rfc7638": fr.huella_rfc7638(pub)}
    casos = []
    for nombre, clave, metodo, ruta, cuerpo in CASOS:
        p = fr.Peticion(metodo, BASE_PUBLICA + ruta, cuerpo.encode() if cuerpo else None)
        r = fr.firmar_peticion(CLAVES[clave], p, CREATED, NONCE)
        casos.append({
            "nombre": nombre,
            "clave": clave,
            "peticion": {"metodo": metodo, "base_publica": BASE_PUBLICA, "ruta": ruta, "cuerpo_utf8": cuerpo},
            "parametros": {"created": CREATED, "nonce": NONCE},
            "esperado": {
                "componentes": fr.componentes(p),
                "content_digest": fr.content_digest(p.cuerpo) if p.cuerpo else None,
                "base_de_firma": r["base"],
                "signature_input": r["signature_input"],
                "keyid": r["keyid"],
            },
            "firma_de_ejemplo": r["firma"],
        })
    perfil = {"estandar": ["RFC 9421", "RFC 9530", "RFC 7638"], "algoritmo": fr.ALGORITMO, "etiqueta": fr.ETIQUETA}
    return {"version": 1, "perfil": perfil, "claves_solo_de_prueba": claves, "casos": casos}


if __name__ == "__main__":
    destino = Path(__file__).with_name("vectores.json")
    destino.write_text(json.dumps(construir(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Escrito {destino}")