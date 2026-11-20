"""Routers de la API; ``app.main`` los registra bajo ``/api/v1``."""

from . import admin
from . import auth
from . import machine
from . import me
from . import scan

__all__ = ["admin", "auth", "machine", "me", "scan"]
