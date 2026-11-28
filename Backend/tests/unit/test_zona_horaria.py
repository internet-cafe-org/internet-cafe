"""BE-19b: la zona horaria de los CSV se resuelve en cualquier sistema operativo.

En Windows, ``zoneinfo`` no trae la base de zonas horarias; sin el paquete ``tzdata`` la
configuración rechaza ``CSV_TIMEZONE`` y ni la API ni las herramientas arrancan.
"""

from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings

REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements.txt"


def test_la_zona_por_defecto_se_resuelve() -> None:
    """``America/Bogota`` carga y la configuración la acepta."""
    zona = Settings.model_fields["csv_timezone"].default

    assert zona == "America/Bogota"
    assert ZoneInfo(zona).key == zona


def test_tzdata_es_dependencia_de_produccion() -> None:
    """``tzdata`` está fijado en ``requirements.txt`` para que Windows no dependa del sistema."""
    lineas = REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert any(linea.startswith("tzdata==") for linea in lineas)
