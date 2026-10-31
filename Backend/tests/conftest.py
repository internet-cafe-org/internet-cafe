import os
import sys

# Asegurar que Backend está en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from httpx import AsyncClient
from freezegun import freeze_time
from app.main import app


@pytest.fixture
async def async_client():
    """Cliente HTTP asíncrono para pruebas de integración."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def frozen_clock():
    """Dispositivo de reloj controlable con freezegun."""  # <- revisa el docstring original
    with freeze_time("2026-10-28 10:00:00") as frozen_time:
        yield frozen_time


@pytest.fixture(autouse=True)
def db_cleanup():
    """Limpieza de base de datos usando TRUNCATE."""
    yield
    # <- aquí va el código que tenías después del yield (el TRUNCATE real)