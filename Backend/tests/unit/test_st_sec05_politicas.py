"""ST-SEC-05: políticas RLS (SRS §12.8). Pruebas sin base de datos."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.database import VARIABLES_RLS, fijar_contexto_rls

MIGRACION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "c3a7e5f1d902_st_sec_05_politicas_rls.py"
)


def _cargar():
    spec = importlib.util.spec_from_file_location("st_sec_05", MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


MIG = _cargar()


def test_la_migracion_sigue_a_st_sec_03() -> None:
    assert MIG.down_revision == "9b4e6d2a8c15"


def test_rls_en_las_tablas_del_srs() -> None:
    assert set(MIG.TABLAS) == {"access_sessions", "login_challenges", "refresh_tokens", "machines"}


@pytest.mark.parametrize("rol", ["svc_admin", "svc_jobs", "svc_app"])
@pytest.mark.parametrize("tabla", ["access_sessions", "login_challenges", "refresh_tokens", "machines"])
def test_admin_tareas_y_transicion_no_tienen_restriccion(rol: str, tabla: str) -> None:
    assert (f"{tabla}_{rol}_todo", tabla, rol, "ALL", "true", "true") in MIG.POLITICAS


@pytest.mark.parametrize("politica", [p for p in MIG.POLITICAS if p[2] in ("svc_web", "svc_machine")])
def test_las_politicas_de_web_y_equipo_dependen_de_una_variable(politica: tuple) -> None:
    nombre, tabla, _rol, comando, using, check = politica
    if tabla == "machines" and comando == "SELECT":
        return  # leer equipos no tiene dueño (SRS: en machines solo se limita el UPDATE)
    if nombre == "equipos_web_bloquear":
        assert check == "false", "la web solo bloquea equipos, nunca los modifica"
        return
    for clausula in (using, check):
        if clausula is not None:
            assert "current_setting('app." in clausula, (nombre, clausula)


def test_las_variables_de_las_politicas_existen_en_la_api() -> None:
    usadas = set()
    for *_, using, check in MIG.POLITICAS:
        for clausula in (using or "", check or ""):
            for trozo in clausula.split("current_setting('app.")[1:]:
                usadas.add(trozo.split("'")[0])
    assert usadas <= VARIABLES_RLS


async def test_una_variable_desconocida_se_rechaza() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    sesion = AsyncMock(spec=AsyncSession)
    sesion.info = {}
    with pytest.raises(ValueError):
        await fijar_contexto_rls(sesion, rol="admin")


async def test_las_sesiones_simuladas_se_ignoran() -> None:
    sesion = AsyncMock()
    await fijar_contexto_rls(sesion, user_id="00000000-0000-0000-0000-000000000001")
    sesion.execute.assert_not_called()
