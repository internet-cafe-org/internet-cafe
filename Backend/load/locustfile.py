r"""Script de carga Locust para la prueba BE-19b (HU-39).

Simula 300 equipos enrolados que, en paralelo, envían latidos cada 60 s y
mantienen un long-poll de ``GET /machine/challenges/wait``.  Usa el firmador
de referencia (SEC-08) para autenticarse por firma RFC 9421 (MACHINE_AUTH_MODE=
signature), igual que lo haría el escritorio real.

Uso (con RATE_LIMIT_ENABLED=false en dev):

    locust -f Backend/load/locustfile.py \\
           --headless -u 300 -r 10 --run-time 10m \\
           --host https://<api-dev>.onrender.com \\
           --html Backend/load/reporte-carga.html \\
           --csv  Backend/load/reporte-carga

Variables de entorno requeridas:
    LOAD_MACHINES_JSON  ruta al JSON generado por prepare_machines.py
    PUBLIC_API_BASE_URL URL pública de la API (igual que la del servidor)

Dependencias (instalar en el venv del Backend):
    locust>=2.29
    cryptography>=42
"""

import json
import os
import secrets
import time
from pathlib import Path

from locust import HttpUser, between, events, task

# ---------------------------------------------------------------------------
# Importar el firmador de referencia (SEC-08) desde contracts/test-vectors.
# ---------------------------------------------------------------------------
import sys

_raiz = Path(__file__).resolve().parents[2]  # …/internet-cafe
sys.path.insert(0, str(_raiz / "contracts" / "test-vectors"))
from firmador_referencia import (  # noqa: E402
    Peticion,
    b64,
    base_de_firma,
    firmar_base,
    huella_rfc7638,
    jwk_publica,
)

# ---------------------------------------------------------------------------
# Cargar datos de los 300 equipos (generados por prepare_machines.py).
# ---------------------------------------------------------------------------
_MACHINES_JSON = os.environ.get(
    "LOAD_MACHINES_JSON",
    str(Path(__file__).parent / "machines.json"),
)
_PUBLIC_BASE = os.environ.get("PUBLIC_API_BASE_URL", "").rstrip("/")

try:
    with open(_MACHINES_JSON, encoding="utf-8") as _f:
        _MAQUINAS: list[dict] = json.load(_f)
except FileNotFoundError:
    # En pruebas sin JSON real se usa una lista vacía; Locust arrancará igual.
    _MAQUINAS = []


def _cabeceras_firma(clave, metodo: str, ruta: str, cuerpo: bytes | None, host: str) -> dict:
    """Genera Signature-Input, Signature y Content-Digest para una petición."""
    uri = (host.rstrip("/") or _PUBLIC_BASE) + ruta
    p = Peticion(metodo=metodo, uri=uri, cuerpo=cuerpo or None)
    created = int(time.time())
    nonce = secrets.token_urlsafe(12)
    keyid = huella_rfc7638(jwk_publica(clave))
    base, params = base_de_firma(p, created, keyid, nonce)
    firma_bytes = firmar_base(clave, base)
    cabeceras = {
        "Signature-Input": f"sig1={params}",
        "Signature": f"sig1=:{b64(firma_bytes)}:",
    }
    if cuerpo:
        import base64
        import hashlib
        digest = base64.b64encode(hashlib.sha256(cuerpo).digest()).decode()
        cabeceras["Content-Digest"] = f"sha-256=:{digest}:"
        cabeceras["Content-Type"] = "application/json"
    return cabeceras


# ---------------------------------------------------------------------------
# Usuario Locust: un equipo enrolado.
# ---------------------------------------------------------------------------

class EquipoEnrolado(HttpUser):
    """Simula un PC enrolado que hace latido cada ~60 s y long-poll continuo."""

    # Pausa entre tareas: en la práctica el latido fija el ritmo (60 s).
    wait_time = between(55, 65)

    # Índice rotativo para distribuir los 300 equipos entre los workers.
    _indice_global: int = 0

    def on_start(self) -> None:
        """Toma el siguiente equipo de la lista y carga su clave privada."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        if not _MAQUINAS:
            self.environment.runner.quit()
            return

        idx = EquipoEnrolado._indice_global % len(_MAQUINAS)
        EquipoEnrolado._indice_global += 1
        maquina = _MAQUINAS[idx]

        self._code = maquina["code"]
        self._keyid = maquina["keyid"]
        # La clave privada PEM se guarda en el JSON (solo dev, nunca producción).
        pem = maquina["private_key_pem"].encode()
        self._clave = load_pem_private_key(pem, password=None)

    def _host_base(self) -> str:
        return (self.host or "").rstrip("/")

    @task(1)
    def latido(self) -> None:
        """POST /machine/heartbeat — se envía cada ~60 s."""
        cuerpo = b"{}"
        ruta = "/machine/heartbeat"
        cabeceras = _cabeceras_firma(
            self._clave, "POST", ruta, cuerpo, self._host_base()
        )
        self.client.post(
            ruta,
            data=cuerpo,
            headers=cabeceras,
            name="POST /machine/heartbeat",
        )

    @task(1)
    def long_poll(self) -> None:
        """GET /machine/challenges/wait — bloquea hasta 30 s en el servidor."""
        ruta = "/machine/challenges/wait?timeout=25"
        cabeceras = _cabeceras_firma(
            self._clave, "GET", ruta, None, self._host_base()
        )
        with self.client.get(
            ruta,
            headers=cabeceras,
            name="GET /machine/challenges/wait",
            timeout=35,
            catch_response=True,
        ) as resp:
            # 200 (approved/waiting) y 204 (sin sesión) son éxito en este endpoint.
            if resp.status_code in (200, 204):
                resp.success()
            else:
                resp.failure(f"estado inesperado: {resp.status_code}")


# ---------------------------------------------------------------------------
# Listener: imprime un resumen al finalizar la prueba.
# ---------------------------------------------------------------------------

@events.quitting.add_listener
def _resumen(environment, **_kw):
    stats = environment.runner.stats
    total = stats.total
    print("\n=== Resumen de carga BE-19b ===")
    print(f"Peticiones totales : {total.num_requests}")
    print(f"Fallos             : {total.num_failures}")
    print(f"RPS (pico)         : {total.max_rps:.1f}")
    print(f"p50 (ms)           : {total.get_response_time_percentile(0.50):.0f}")
    print(f"p95 (ms)           : {total.get_response_time_percentile(0.95):.0f}")
    print(f"p99 (ms)           : {total.get_response_time_percentile(0.99):.0f}")
