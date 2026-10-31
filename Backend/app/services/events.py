"""Módulo de eventos en memoria para notificación de equipos (SRS §8.1 / BE-06 / BE-07b).

Proporciona el despachador de eventos para despertar a los equipos en espera (long-poll)
cuando un reto QR es reclamado exitosamente en POST /scan/claim.
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Mapa en memoria de eventos por ID de equipo: machine_id -> List[asyncio.Event]
_listeners: Dict[uuid.UUID, List[asyncio.Event]] = {}
# Almacén temporal del payload al despertar
_payloads: Dict[uuid.UUID, Any] = {}


def subscribe(machine_id: uuid.UUID) -> asyncio.Event:
    """Suscribe un listener (long-poll) para recibir notificaciones de un equipo."""
    event = asyncio.Event()
    if machine_id not in _listeners:
        _listeners[machine_id] = []
    _listeners[machine_id].append(event)
    return event


def unsubscribe(machine_id: uuid.UUID, event: asyncio.Event) -> None:
    """Elimina un listener suscrito para evitar fugas de memoria."""
    if machine_id in _listeners:
        if event in _listeners[machine_id]:
            _listeners[machine_id].remove(event)
        if not _listeners[machine_id]:
            del _listeners[machine_id]
            _payloads.pop(machine_id, None)


def notify(machine_id: uuid.UUID, data: Any = None) -> None:
    """Notifica a todos los listeners esperando por el equipo machine_id.

    Despierta a cualquier worker de long-poll asociado tras el COMMIT del claim.
    """
    if data is not None:
        _payloads[machine_id] = data

    listeners = _listeners.get(machine_id, [])
    if listeners:
        logger.info("Notificando a %d listener(s) del equipo %s", len(listeners), machine_id)
        for event in list(listeners):
            event.set()
    else:
        logger.debug("No hay listeners activos en espera para el equipo %s", machine_id)


def get_event_payload(machine_id: uuid.UUID) -> Any:
    """Obtiene el payload más reciente notificado para el equipo."""
    return _payloads.get(machine_id)
