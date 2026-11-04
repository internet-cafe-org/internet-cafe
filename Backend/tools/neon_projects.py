"""Crea los proyectos de Neon `dev` y `prod` con el tope de cómputo de OPS-02.

Cada entorno es un PROYECTO distinto de Neon (no solo una rama), con el cómputo fijado
en 0,25 CU: `autoscaling_limit_min_cu = autoscaling_limit_max_cu = 0.25`. Con el tope en
el mínimo, ningún error de código puede gastar más de 0,25 CU-h por hora del plan gratuito
(SRS §3: 100 CU-h/mes por proyecto).

Por defecto NO hace nada en la red: imprime el cuerpo que enviaría (dry-run). Con
`--apply` hace `POST https://console.neon.tech/api/v2/projects` usando la clave de la
variable de entorno NEON_API_KEY. La clave y las cadenas de conexión de la respuesta
(que incluyen la contraseña del propietario) NUNCA se imprimen: la contraseña de
`neondb_owner` se consulta en la consola de Neon y se usa solo para ejecutar
`db/bootstrap_roles.sql`.

    python -m tools.neon_projects --env dev                       # dry-run
    NEON_API_KEY=... python -m tools.neon_projects --env prod --apply
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

NEON_API_URL = "https://console.neon.tech/api/v2/projects"
TOPE_CU = 0.25
ENTORNOS = ("dev", "prod")
PG_VERSION = 17  # SRS §3: PostgreSQL 17
REGION_POR_DEFECTO = "aws-us-east-2"


def construir_payload(
    entorno: str, region: str = REGION_POR_DEFECTO, pg_version: int = PG_VERSION
) -> dict[str, Any]:
    """Cuerpo de `POST /projects` para el entorno indicado (sin red ni secretos)."""
    if entorno not in ENTORNOS:
        raise ValueError(f"entorno debe ser uno de {ENTORNOS}")
    return {
        "project": {
            "name": f"internet-cafe-{entorno}",
            "region_id": region,
            "pg_version": pg_version,
            "default_endpoint_settings": {
                "autoscaling_limit_min_cu": TOPE_CU,
                "autoscaling_limit_max_cu": TOPE_CU,
            },
        }
    }


def crear_proyecto(payload: dict[str, Any], api_key: str) -> dict[str, str]:
    """Crea el proyecto y devuelve solo datos no sensibles de la respuesta."""
    peticion = urllib.request.Request(
        NEON_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:  # noqa: S310 (URL fija https)
            cuerpo = json.load(respuesta)
    except urllib.error.HTTPError as exc:
        # Solo el código: el cuerpo de error puede repetir datos de la petición
        raise RuntimeError(f"Neon respondió HTTP {exc.code}") from None
    proyecto = cuerpo.get("project", {})
    return {
        "id": str(proyecto.get("id", "")),
        "name": str(proyecto.get("name", "")),
        "region_id": str(proyecto.get("region_id", "")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea proyectos de Neon con tope de 0,25 CU.")
    parser.add_argument("--env", choices=ENTORNOS, required=True)
    parser.add_argument("--region", default=REGION_POR_DEFECTO)
    parser.add_argument("--apply", action="store_true", help="Crear de verdad (sin esto: dry-run).")
    args = parser.parse_args(argv)

    payload = construir_payload(args.env, args.region)
    if not args.apply:
        print("DRY-RUN (no se llamó a Neon). Cuerpo de la petición:")
        print(json.dumps(payload, indent=2))
        return 0

    api_key = os.environ.get("NEON_API_KEY")
    if not api_key:
        print("ERROR: define NEON_API_KEY en el entorno.", file=sys.stderr)
        return 2
    try:
        creado = crear_proyecto(payload, api_key)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(creado, indent=2))
    print(
        "Siguiente paso: obtén la contraseña de neondb_owner en la consola de Neon y "
        "ejecuta db/bootstrap_roles.sql (ver db/README.md)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
