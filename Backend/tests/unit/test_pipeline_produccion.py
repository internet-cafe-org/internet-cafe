"""Pipeline de producción (QA-17): estructura de `.github/workflows/deploy-prod.yml`.

Sin red, sin base y sin GitHub: se lee el YAML y se comprueban las garantías que el
pipeline promete (solo etiquetas `v*`, aprobación del environment `prod`, orden de los
pasos de la API, secretos solo por `secrets.*` y web con la CLI de Vercel).
"""

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
RUTA = RAIZ / ".github" / "workflows" / "deploy-prod.yml"

# Únicos secretos que el pipeline puede leer; uno nuevo exige actualizar esta lista a propósito.
SECRETOS_PERMITIDOS = {
    "DATABASE_URL_MIGRATOR",
    "RENDER_DEPLOY_HOOK",
    "VERCEL_TOKEN",
    "VERCEL_ORG_ID",
    "VERCEL_PROJECT_ID",
}


@pytest.fixture(scope="module")
def texto() -> str:
    return RUTA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def flujo(texto: str) -> dict:
    return yaml.safe_load(texto)


def _disparadores(flujo: dict) -> dict:
    # PyYAML (YAML 1.1) lee la clave `on` como el booleano True
    return flujo["on"] if "on" in flujo else flujo[True]


def _indice_paso(pasos: list[dict], fragmento: str) -> int:
    """Devuelve la posición del primer paso cuyo nombre contiene `fragmento`."""
    for i, paso in enumerate(pasos):
        if fragmento.lower() in paso.get("name", "").lower():
            return i
    raise AssertionError(f"No hay un paso que contenga {fragmento!r} en su nombre")


def _comandos(job: dict) -> str:
    return "\n".join(paso.get("run", "") for paso in job["steps"])


def test_se_dispara_solo_con_etiquetas_v(flujo: dict) -> None:
    disparadores = _disparadores(flujo)
    assert set(disparadores) == {"push"}
    assert disparadores["push"] == {"tags": ["v*"]}  # sin `branches`: un push a main no despliega prod


def test_permisos_minimos(flujo: dict) -> None:
    assert flujo["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("job", ["api", "web"])
def test_cada_job_exige_el_environment_prod(flujo: dict, job: str) -> None:
    assert flujo["jobs"][job]["environment"] == "prod"


def test_la_web_espera_a_la_api(flujo: dict) -> None:
    necesita = flujo["jobs"]["web"]["needs"]
    assert necesita in ("api", ["api"])


def test_la_api_corre_con_app_env_prod(flujo: dict) -> None:
    assert flujo["jobs"]["api"]["env"]["APP_ENV"] == "prod"


def test_una_migracion_nunca_se_cancela(flujo: dict) -> None:
    concurrencia = flujo["jobs"]["api"]["concurrency"]
    assert concurrencia["group"] == "prod-db"
    assert concurrencia["cancel-in-progress"] is False


def test_la_etiqueta_debe_salir_de_main(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    assert pasos[0]["uses"].startswith("actions/checkout@")
    assert pasos[0]["with"]["fetch-depth"] == 0  # sin historial completo no hay merge-base
    paso = pasos[_indice_paso(pasos, "sale de main")]
    assert "merge-base --is-ancestor" in paso["run"]
    assert "origin/main" in paso["run"]


def test_orden_de_los_pasos_de_la_api(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    orden = [
        _indice_paso(pasos, "sale de main"),
        _indice_paso(pasos, "una sola cabeza"),
        _indice_paso(pasos, "Migrar"),
        _indice_paso(pasos, "deploy hook"),
        _indice_paso(pasos, "humo"),
    ]
    assert orden == sorted(orden)
    assert len(set(orden)) == len(orden)


def test_la_cabeza_unica_exige_exactamente_una(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    comando = pasos[_indice_paso(pasos, "una sola cabeza")]["run"]
    assert "alembic heads" in comando
    assert '-ne 1' in comando
    assert "exit 1" in comando


def test_migra_con_el_rol_migrador_y_sin_la_base_de_la_app(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    paso = pasos[_indice_paso(pasos, "Migrar")]
    esperado = "${{ secrets.DATABASE_URL_MIGRATOR }}"
    assert paso["env"]["DATABASE_URL"] == esperado
    assert paso["env"]["DATABASE_URL_MIGRATOR"] == esperado
    assert "alembic upgrade head" in paso["run"]


def test_el_deploy_hook_sale_de_un_secreto(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    paso = pasos[_indice_paso(pasos, "deploy hook")]
    assert paso["env"]["RENDER_DEPLOY_HOOK"] == "${{ secrets.RENDER_DEPLOY_HOOK }}"
    assert 'curl -fsS -o /dev/null -X POST "$RENDER_DEPLOY_HOOK"' in paso["run"]


def test_el_humo_de_la_api_prueba_healthz_y_readyz(flujo: dict) -> None:
    pasos = flujo["jobs"]["api"]["steps"]
    paso = pasos[_indice_paso(pasos, "humo")]
    assert paso["env"]["PROD_API_URL"] == "${{ vars.PROD_API_URL }}"
    assert 'probar "$PROD_API_URL/healthz"' in paso["run"]
    assert 'probar "$PROD_API_URL/readyz"' in paso["run"]


def test_la_web_usa_la_cli_de_vercel_en_produccion(flujo: dict) -> None:
    comandos = _comandos(flujo["jobs"]["web"])
    pasos = flujo["jobs"]["web"]["steps"]
    assert "vercel pull --yes --environment=production" in comandos
    assert "vercel build --prod" in comandos
    assert "vercel deploy --prebuilt --prod" in comandos
    assert _indice_paso(pasos, "Traer") < _indice_paso(pasos, "Construir") < _indice_paso(pasos, "Desplegar")


def test_la_web_recibe_las_credenciales_de_vercel_por_secretos(flujo: dict) -> None:
    entorno = flujo["jobs"]["web"]["env"]
    for nombre in ("VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"):
        assert entorno[nombre] == f"${{{{ secrets.{nombre} }}}}"


def test_solo_se_leen_los_secretos_permitidos(texto: str) -> None:
    usados = set(re.findall(r"secrets\.([A-Z0-9_]+)", texto))
    assert usados == SECRETOS_PERMITIDOS


def test_sin_valores_sensibles_en_el_archivo(texto: str) -> None:
    sin_comentarios = "\n".join(linea.split(" #")[0] for linea in texto.splitlines())
    assert not re.search(r"://[^/\s:@$]+:[^/\s@$]+@", sin_comentarios), "URL con usuario y contraseña"
    assert "api.render.com/deploy" not in sin_comentarios, "deploy hook escrito en el archivo"
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", sin_comentarios)
    # Los comandos de Vercel no reciben el token por la línea de comandos (se vería en los logs)
    assert "--token" not in sin_comentarios
