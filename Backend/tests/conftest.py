import os
import sys

# Asegurar que Backend está en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from httpx import AsyncClient, ASGITransport
from freezegun import freeze_time
from app.main import app


@pytest.fixture
async def async_client():
    """Cliente HTTP asíncrono para pruebas de integración."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def frozen_clock():
    """Dispositivo de reloj controlable con freezegun."""  # <- revisa el docstring original
    with freeze_time("2026-10-28 10:00:00") as frozen_time:
        yield frozen_time


@pytest.fixture(autouse=True)
def limites_en_cero():
    """Reinicia el rate limit en memoria (SEC-09) para que cada prueba empiece de cero."""
    from app.security.limites import limitador

    limitador.reiniciar()
    yield
    limitador.reiniciar()


@pytest.fixture(autouse=True)
def db_cleanup():
    """Limpieza de base de datos usando TRUNCATE."""
    yield
    # <- aquí va el código que tenías después del yield (el TRUNCATE real)

@pytest.fixture(autouse=True)
def llaves_pii_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura llaves PII por defecto si están vacías (SEC-06)."""
    from app.config import settings

    if not settings.data_enc_keys:
        monkeypatch.setattr(settings, "data_enc_keys", '{"1": "' + "a" * 64 + '"}')
    if not settings.blind_index_key:
        monkeypatch.setattr(settings, "blind_index_key", "a" * 64)
