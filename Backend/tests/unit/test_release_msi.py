"""Release del instalador (OPS-14): estructura de `.github/workflows/release-msi.yml`.

Sin red y sin GitHub: se lee el YAML y se comprueban sus garantías (etiqueta de `main`,
environment `prod`, escritura solo en el job que publica y verificación del `.msi`).
"""

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
RUTA = RAIZ / ".github" / "workflows" / "release-msi.yml"


@pytest.fixture(scope="module")
def jobs() -> dict:
    """Jobs del workflow."""
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))["jobs"]


def _paso(job: dict, texto: str) -> int:
    """Devuelve la posición del primer paso que contiene el texto.

    Args:
        job: Job del workflow.
        texto: Texto que se busca en el nombre o en el comando.

    Returns:
        Índice del paso.

    Raises:
        StopIteration: Si ningún paso lo contiene.
    """
    return next(
        i for i, p in enumerate(job["steps"]) if texto in p.get("name", "") + p.get("run", "")
    )


def test_la_etiqueta_debe_salir_de_main_antes_de_construir(jobs: dict) -> None:
    """Igual que `deploy-prod`: un commit fuera de `main` no genera instalador."""
    release = jobs["release"]
    verificar = _paso(release, "git merge-base --is-ancestor")

    assert release["steps"][0]["with"]["fetch-depth"] == 0
    assert "origin/main" in release["steps"][verificar]["run"]
    assert verificar < _paso(release, "gradle -p desktop jpackageMsi")


def test_el_instalador_de_prod_exige_el_environment_y_la_etiqueta(jobs: dict) -> None:
    """Se construye solo con etiquetas `v*` y con la aprobación del environment `prod`."""
    assert jobs["release"]["environment"] == "prod"
    assert "refs/tags/v" in jobs["release"]["if"]


def test_solo_el_job_que_publica_puede_escribir(jobs: dict) -> None:
    """El job que ejecuta Gradle no recibe `contents: write` ni deja el token en git."""
    con_escritura = [n for n, j in jobs.items() if "write" in j.get("permissions", {}).values()]

    assert con_escritura == ["publicar"]
    assert jobs["publicar"]["needs"] == "release"
    assert not any("gradle" in str(p).lower() for p in jobs["publicar"]["steps"])
    for nombre in ("prueba", "release"):
        assert jobs[nombre]["steps"][0]["with"]["persist-credentials"] is False


def test_el_msi_se_verifica_antes_de_subirlo(jobs: dict) -> None:
    """`verificar-msi.ps1` corre antes de subir el artefacto y se comprueba el SHA-256."""
    for nombre in ("prueba", "release"):
        subir = next(
            i
            for i, p in enumerate(jobs[nombre]["steps"])
            if "upload-artifact" in p.get("uses", "")
        )
        assert _paso(jobs[nombre], "verificar-msi.ps1") < subir
    publicar = jobs["publicar"]["steps"][-1]["run"]
    assert publicar.index("sha256sum --check") < publicar.index("gh release")
