"""
ST-OPS-01 - Pruebas del camino feliz: dominio verificado en Resend (SPF, DKIM y DMARC).

Solo usa la libreria estandar + pytest. Consulta DNS por HTTPS (Cloudflare),
asi que no necesita instalar dnspython ni depende del DNS local.

Uso (PowerShell):
    $env:DOMINIO_REENVIAR = "tudominio.com"
    python -m pytest tests/ops -v

Variables opcionales:
    SUBDOMINIO_ENVIO  subdominio de envio configurado en Resend (por defecto "send")
"""
import json
import os
import urllib.parse
import urllib.request

import pytest

DOMINIO = os.getenv("DOMINIO_REENVIAR", "").strip()
SUBDOMINIO_ENVIO = os.getenv("SUBDOMINIO_ENVIO", "send").strip()

pytestmark = pytest.mark.skipif(
    not DOMINIO, reason="Define la variable de entorno DOMINIO_REENVIAR"
)


def consultar_dns(nombre: str, tipo: str) -> list[str]:
    """Devuelve los valores del registro DNS (lista vacia si no existe)."""
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode(
        {"name": nombre, "type": tipo}
    )
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        datos = json.load(resp)
    valores = []
    for respuesta in datos.get("Answer", []):
        valor = respuesta["data"].strip('"').replace('" "', "")
        valores.append(valor)
    return valores


def test_spf_en_subdominio_de_envio():
    registros = consultar_dns(f"{SUBDOMINIO_ENVIO}.{DOMINIO}", "TXT")
    spf = [r for r in registros if r.lower().startswith("v=spf1")]
    assert spf, f"No hay registro SPF en {SUBDOMINIO_ENVIO}.{DOMINIO}"
    assert any("amazonses.com" in r for r in spf), f"SPF sin include de Resend/SES: {spf}"


def test_mx_de_retorno_en_subdominio_de_envio():
    registros = consultar_dns(f"{SUBDOMINIO_ENVIO}.{DOMINIO}", "MX")
    assert any("amazonses.com" in r for r in registros), (
        f"Falta el MX de retorno de Resend en {SUBDOMINIO_ENVIO}.{DOMINIO}: {registros}"
    )


def test_dkim_publicado():
    registros = consultar_dns(f"resend._domainkey.{DOMINIO}", "TXT")
    assert any("p=" in r for r in registros), (
        f"No hay llave publica DKIM en resend._domainkey.{DOMINIO}"
    )


def test_dmarc_publicado():
    registros = consultar_dns(f"_dmarc.{DOMINIO}", "TXT")
    dmarc = [r for r in registros if r.upper().startswith("V=DMARC1")]
    assert dmarc, f"No hay registro DMARC en _dmarc.{DOMINIO}"
    assert "p=" in dmarc[0].lower(), f"DMARC sin politica (p=): {dmarc[0]}"