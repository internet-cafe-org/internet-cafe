"""Rate limit por cuenta y por IP (SEC-09, SRS §12.2).

Cubre ``/auth/*``, ``/scan/claim`` y ``/machine/enroll``. Primero se limita por
cuenta y luego por IP, cada uno con una ventana deslizante de 60 s. El refresh
solo se limita por su propio token: no cuenta para el límite por IP, para que
varias pestañas detrás de la misma red no se bloqueen entre sí.

El estado vive en memoria: Render dev corre con un solo worker (OPS-03). Las
claves de cuenta se guardan como SHA-256, nunca el correo en claro.

**IP del cliente.** Detrás de proxies, la IP real está en ``X-Forwarded-For``.
Solo se confía en los saltos que agregan los proxies propios, y su número
depende de la ruta: la web pasa por Vercel y Render (``RATE_LIMIT_SALTOS_WEB``)
y el escritorio va directo a Render (``RATE_LIMIT_SALTOS_EQUIPO``). Se toma la
entrada que está ``saltos`` posiciones antes del final; lo que el cliente haya
escrito más a la izquierda se ignora.
"""

import hashlib
import math
import time
from collections import deque
from enum import Enum
from threading import Lock

from fastapi import Request

from app.config import settings
from app.errors import AppError, ErrorCode
from app.logger import obtener_logger

logger = obtener_logger("limites")

VENTANA_S = 60.0


class Origen(Enum):
    """Por dónde llega la petición, para saber cuántos saltos de proxy confiar."""

    WEB = "web"
    EQUIPO = "equipo"


class LimitadorVentana:
    """Contador de ventana deslizante en memoria."""

    def __init__(self) -> None:
        """Crea el limitador vacío."""
        self._marcas: dict[str, deque[float]] = {}
        self._candado = Lock()

    def registrar(self, clave: str, limite: int, ahora: float | None = None) -> int:
        """Cuenta una petición y dice cuánto esperar si se pasó del límite.

        Args:
            clave: Identificador de lo que se limita (cuenta, IP o token).
            limite: Peticiones permitidas en la ventana.
            ahora: Reloj monótono en segundos; solo para las pruebas.

        Returns:
            0 si la petición se permite; si no, los segundos para ``Retry-After``.
        """
        ahora = time.monotonic() if ahora is None else ahora
        with self._candado:
            marcas = self._marcas.setdefault(clave, deque())
            while marcas and marcas[0] <= ahora - VENTANA_S:
                marcas.popleft()
            if len(marcas) >= limite:
                return max(1, math.ceil(marcas[0] + VENTANA_S - ahora))
            marcas.append(ahora)
            return 0

    def reiniciar(self) -> None:
        """Olvida todos los contadores (pruebas y reinicios)."""
        with self._candado:
            self._marcas.clear()


limitador = LimitadorVentana()


def _huella(valor: str) -> str:
    """Resume un identificador para no guardarlo en claro.

    Args:
        valor: Correo, token o código.

    Returns:
        SHA-256 en hex del valor normalizado.
    """
    return hashlib.sha256(valor.strip().lower().encode("utf-8")).hexdigest()


def ip_del_cliente(request: Request, origen: Origen) -> str:
    """Obtiene la IP del cliente respetando solo los saltos de proxy confiables.

    Args:
        request: Petición entrante.
        origen: ``WEB`` (Vercel + Render) o ``EQUIPO`` (solo Render).

    Returns:
        La IP del cliente, o la del socket si no hay suficientes saltos.
    """
    saltos = (
        settings.rate_limit_saltos_web if origen is Origen.WEB else settings.rate_limit_saltos_equipo
    )
    reenviada = request.headers.get("x-forwarded-for", "")
    ips = [ip.strip() for ip in reenviada.split(",") if ip.strip()]
    if saltos > 0 and len(ips) >= saltos:
        return ips[-saltos]
    return request.client.host if request.client else "desconocida"


def _rechazar(espera: int, tipo: str, ruta: str) -> None:
    """Lanza el 429 con ``Retry-After`` y lo registra sin datos personales.

    Args:
        espera: Segundos que hay que esperar.
        tipo: ``cuenta``, ``ip`` o ``token``.
        ruta: Grupo de rutas que se limitó.

    Raises:
        AppError: Siempre, ``RATE_LIMITED``.
    """
    logger.warning(
        "Rate limit",
        extra={"datos": {"evento": "seguridad.rate_limit", "por": tipo, "ruta": ruta}},
    )
    raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(espera)})


def limitar(
    request: Request,
    ruta: str,
    *,
    cuenta: str | None = None,
    origen: Origen = Origen.WEB,
    contar_ip: bool = True,
) -> None:
    """Aplica el rate limit de una petición: primero por cuenta y luego por IP.

    No hace nada si ``RATE_LIMIT_ENABLED`` es ``false``.

    Args:
        request: Petición entrante, para leer la IP.
        ruta: Grupo de rutas (p. ej. ``auth.login``); los contadores son por grupo.
        cuenta: Correo, id de usuario, token o código que identifica la cuenta.
        origen: De dónde llega la petición, para los saltos de ``X-Forwarded-For``.
        contar_ip: ``False`` para que no cuente en el límite por IP (refresh).

    Raises:
        AppError: 429 ``RATE_LIMITED`` con ``Retry-After`` si se superó un límite.
    """
    if not settings.rate_limit_enabled:
        return
    if cuenta:
        espera = limitador.registrar(f"{ruta}:cuenta:{_huella(cuenta)}", settings.rate_limit_por_cuenta)
        if espera:
            _rechazar(espera, "cuenta", ruta)
    if contar_ip:
        ip = ip_del_cliente(request, origen)
        espera = limitador.registrar(f"{ruta}:ip:{ip}", settings.rate_limit_por_ip)
        if espera:
            _rechazar(espera, "ip", ruta)
