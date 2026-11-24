"""BE-22: los insumos de los manuales coinciden con el código.

Evita que el catálogo, las reglas visibles o los mensajes del CLI cambien y el documento
``docs/manuales/insumos/backend.md`` quede con información vieja.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.errors import CATALOGO, ErrorCode
from app.models import SessionEndReason
from app.services import challenges

RAIZ = Path(__file__).resolve().parents[3]
DOC = (RAIZ / "docs" / "manuales" / "insumos" / "backend.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("codigo", list(ErrorCode), ids=lambda c: c.value)
def test_cada_error_esta_con_su_mensaje(codigo: ErrorCode) -> None:
    """Cada código aparece con su HTTP, título y mensaje por defecto."""
    spec = CATALOGO[codigo]

    assert f"| `{codigo.value}` | {spec.status} | {spec.title} | {spec.detail} |" in DOC


@pytest.mark.parametrize("motivo", list(SessionEndReason), ids=lambda m: m.value)
def test_cada_motivo_de_cierre_esta_documentado(motivo: SessionEndReason) -> None:
    """Los motivos de cierre del modelo están en la tabla."""
    assert f"| `{motivo.value}` |" in DOC


def test_las_reglas_visibles_coinciden_con_la_configuracion() -> None:
    """QR de 60 s que rota a los 45 s, cierre a los 3 min y bloqueo de 5 intentos y 15 min."""
    campos = Settings.model_fields

    assert (challenges.CHALLENGE_TTL_S, challenges.ROTATE_AFTER_S) == (60, 45)
    assert campos["heartbeat_timeout_s"].default == 180
    assert campos["inactividad_intervalo_s"].default == 30
    assert campos["login_max_intentos"].default == 5
    assert campos["login_bloqueo_minutos"].default == 15
    for texto in ("El QR dura 60 s", "cada 45 s", "3 min sin latido", "bloquean el inicio de sesión 15 min"):
        assert texto in DOC


@pytest.mark.parametrize(
    ("archivo", "mensaje"),
    [
        ("tools/admin_cli.py", "indica el correo con --email o ADMIN_CLI_EMAIL."),
        ("tools/admin_cli.py", "define BLIND_INDEX_KEY (la misma de la API)."),
        ("tools/admin_cli.py", "define ADMIN_PASSWORD en el entorno."),
        ("app/services/usuarios.py", "El correo no es válido."),
        ("app/services/usuarios.py", "Ya existe una cuenta con ese correo."),
        ("app/services/usuarios.py", "No existe una cuenta con ese correo."),
    ],
)
def test_los_mensajes_del_cli_son_los_del_codigo(archivo: str, mensaje: str) -> None:
    """Los mensajes de error del CLI están en el documento y en el código."""
    assert f"`ERROR: {mensaje}`" in DOC
    assert mensaje in (RAIZ / "Backend" / archivo).read_text(encoding="utf-8")
