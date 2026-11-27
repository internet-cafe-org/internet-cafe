"""Ejecuta latido y long-poll firmados con una identidad por usuario de Locust."""

from collections import deque
from urllib.parse import urlsplit

import gevent
from locust import HttpUser, constant, events, task
from locust.runners import LocalRunner

from tools.carga.datos import (
    ARCHIVO_CLAVES,
    CUERPO_LATIDO,
    LATIDO,
    RETO_EN_ESPERA,
    TOTAL_EQUIPOS,
    cabeceras_firmadas,
    leer_claves,
)

URL_DEV = "https://internet-cafe-tq03.onrender.com"
POLL = f"{RETO_EN_ESPERA}?timeout=25"
INTERVALO_LATIDO = 60


@events.init.add_listener
def preparar(environment, **_kwargs) -> None:
    """Valida la corrida de un solo proceso y carga el conjunto local de claves."""
    opciones = environment.parsed_options
    if not isinstance(environment.runner, LocalRunner) or not opciones.headless:
        raise SystemExit("Ejecuta Locust en un solo proceso con --headless.")
    origen = (environment.host or "").rstrip("/")
    url = urlsplit(origen)
    local = (
        url.scheme == "http"
        and url.hostname in {"localhost", "127.0.0.1"}
        and not (url.username or url.path or url.query or url.fragment)
    )
    if origen != URL_DEV and not local:
        raise SystemExit("Indica la URL de Render dev o una API local como --host.")
    minimo = 1 if local else TOTAL_EQUIPOS
    if not minimo <= (opciones.num_users or 0) <= TOTAL_EQUIPOS:
        raise SystemExit(f"Indica entre {minimo} y {TOTAL_EQUIPOS} usuarios para este destino.")
    try:
        Equipo.claves = deque(leer_claves(ARCHIVO_CLAVES))
    except (OSError, ValueError):
        raise SystemExit("Prepara el archivo .env.locust.json antes de ejecutar Locust.") from None


class Equipo(HttpUser):
    """Simula un equipo ocioso, con latido independiente de la espera del QR."""

    claves = deque()
    wait_time = constant(1)

    def on_start(self) -> None:
        """Reserva una identidad y arranca el latido en paralelo."""
        self.clave = self.claves.popleft()
        self.latidos = gevent.spawn(self.enviar_latidos)

    def on_stop(self) -> None:
        """Detiene el latido al terminar el usuario."""
        self.latidos.kill()

    def enviar_latidos(self) -> None:
        """Envía un latido inicial y repite cada 60 segundos."""
        while True:
            self.peticion_firmada("POST", LATIDO, LATIDO, CUERPO_LATIDO)
            gevent.sleep(INTERVALO_LATIDO)

    @task
    def esperar(self) -> None:
        """Realiza long-poll con el máximo de espera que admite la API."""
        self.peticion_firmada("GET", POLL, RETO_EN_ESPERA)

    def peticion_firmada(
        self, metodo: str, ruta: str, nombre: str, cuerpo: bytes | None = None
    ) -> None:
        """Registra la ruta y el estado HTTP en Locust sin volcar cuerpos ni cabeceras."""
        cabeceras = cabeceras_firmadas(self.clave, metodo, self.host.rstrip("/") + ruta, cuerpo)
        with self.client.request(
            metodo,
            ruta,
            name=nombre,
            headers=cabeceras,
            data=cuerpo,
            timeout=35,
            allow_redirects=False,
            catch_response=True,
        ) as respuesta:
            if respuesta.status_code != 200:
                respuesta.failure(f"HTTP {respuesta.status_code}" if respuesta.status_code else "Error de conexión")
