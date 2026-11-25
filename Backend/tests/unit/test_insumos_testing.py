"""QA-19: los mensajes citados en los insumos de Testing existen en la aplicación.

Cada texto entre «» de ``docs/manuales/insumos/testing.md`` debe aparecer tal cual en el código
de la web (``frontend/src``) o del escritorio (``desktop/src/main``). Así el documento no se queda
con mensajes que la aplicación ya no muestra. ``<equipo>`` marca un dato que cambia.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
DOC = (RAIZ / "docs" / "manuales" / "insumos" / "testing.md").read_text(encoding="utf-8")

_CITA = re.compile(r"«([^«»]+)»")
_MARCADOR = re.compile(r"<[^<>]+>")
_JAVA_CONCATENACION = re.compile(r'"\s*\+\s*"')
_ESPACIOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    return _ESPACIOS.sub(" ", texto)


def _corpus() -> str:
    """Código de la web y del escritorio, con espacios y saltos de línea unificados."""
    partes: list[str] = []
    for ruta in sorted((RAIZ / "frontend" / "src").rglob("*")):
        if ruta.suffix in {".vue", ".ts"} and "__tests__" not in ruta.parts:
            partes.append(ruta.read_text(encoding="utf-8"))
    for ruta in sorted((RAIZ / "desktop" / "src" / "main").rglob("*")):
        if ruta.suffix in {".java", ".fxml"}:
            texto = ruta.read_text(encoding="utf-8")
            # "texto " + "partido" en Java es un solo mensaje en pantalla
            texto = _JAVA_CONCATENACION.sub("", texto).replace("\\n", " ")
            partes.append(texto)
    return _normalizar("\n".join(partes))


CORPUS = _corpus()
CITAS = sorted({_normalizar(c.strip()) for c in _CITA.findall(DOC)})


def test_el_documento_cita_mensajes() -> None:
    """Protege contra un cambio de formato que deje la prueba sin nada que revisar."""
    assert len(CITAS) >= 20


@pytest.mark.parametrize("cita", CITAS)
def test_cada_mensaje_citado_existe_en_la_aplicacion(cita: str) -> None:
    fragmentos = [f.strip() for f in _MARCADOR.split(cita) if f.strip()]

    faltan = [f for f in fragmentos if f not in CORPUS]

    assert not faltan, f"No está en frontend/src ni en desktop/src/main: {faltan}"
