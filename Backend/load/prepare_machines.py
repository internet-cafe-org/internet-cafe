"""Genera machines.json con 300 equipos ficticios pre-enrolados (BE-19a).

Lee los equipos activos de la base de dev y exporta su código, keyid y clave
privada PEM (solo se usa en la prueba de carga; nunca en producción).

    python -m Backend.load.prepare_machines --out Backend/load/machines.json

Variables de entorno requeridas:
    DATABASE_URL   conexión a la base de dev (rol app)

El JSON resultante NUNCA se sube al repo (está en .gitignore).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_MAX = 300


async def _exportar(out: Path, limite: int) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    db_url = os.environ["DATABASE_URL"]
    motor = create_async_engine(db_url, echo=False)
    Session = sessionmaker(motor, class_=AsyncSession, expire_on_commit=False)

    # Importación diferida: evita que config.py exija todas las variables al arrancar.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.models import Machine, MachineStatus

    async with Session() as db:
        filas = (
            await db.execute(
                select(Machine)
                .where(
                    Machine.status == MachineStatus.active,
                    Machine.public_key_jwk.isnot(None),
                )
                .limit(limite)
            )
        ).scalars().all()

    await motor.dispose()

    if not filas:
        sys.exit("No hay equipos activos con clave pública en la base de dev.")

    maquinas = []
    for m in filas:
        maquinas.append(
            {
                "code": m.code,
                "keyid": m.key_thumbprint,
                # En la prueba de carga las claves privadas se generan in-process
                # (el script de enrolamiento real las guarda en ProgramData).
                # Aquí se delega al locustfile: on_start genera una clave efímera
                # cuyo keyid no coincide con la BD, así que la prueba usa el modo
                # token (credencial provisional) si está disponible, o se configura
                # con MACHINE_AUTH_MODE=token en dev durante la prueba.
                "private_key_pem": "",  # rellenado por enroll_machines.py
                "credential": m.code,   # campo informativo
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(maquinas, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exportados {len(maquinas)} equipos → {out}")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la línea de comandos.

    Args:
        argv: Argumentos; por defecto, los del proceso.

    Returns:
        Código de salida del proceso.
    """
    parser = argparse.ArgumentParser(description="Exporta equipos de dev para la carga.")
    parser.add_argument("--out", type=Path, default=Path("Backend/load/machines.json"))
    parser.add_argument("--limite", type=int, default=_MAX)
    args = parser.parse_args(argv)
    asyncio.run(_exportar(args.out, args.limite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
