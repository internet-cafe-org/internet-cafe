"""Semilla idempotente del entorno dev (QA-02a).

Crea o actualiza el administrador de dev, las salas y los equipos, y, si se piden,
genera N códigos de enrolamiento de un solo uso para los equipos que aún no están
enrolados. Volver a correrla no duplica nada: el administrador se busca por su índice
ciego, las salas por nombre y los equipos por código. Los códigos sí son nuevos en cada
ejecución, porque se piden a demanda.

Solo corre con APP_ENV=dev (la semilla del piloto es QA-02b). Lee del entorno:
    DATABASE_URL          conexión a la base de dev
    BLIND_INDEX_KEY       la misma clave que usa la API de dev (índice ciego del correo)
    SEED_ADMIN_PASSWORD   contraseña del administrador de dev (política de 10 a 128)
    SEED_ADMIN_EMAIL      opcional, por defecto admin@dev.invalid

La contraseña y los códigos NUNCA se imprimen. Los códigos en claro solo se escriben
en el archivo de --salida-codigos; en la base queda su SHA-256.

    python -m tools.seed_dev
    python -m tools.seed_dev --codigos 3 --salida-codigos codigos.txt
"""

import argparse
import asyncio
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN_EMAIL_POR_DEFECTO = "admin@dev.invalid"
ADMIN_NOMBRE = "Administrador Dev"
EDIFICIO_DEV = "Dev"
MAX_CODIGOS = 50


@dataclass
class Resumen:
    admin_creado: bool
    salas_creadas: int
    equipos_creados: int
    codigos: list[tuple[str, str]]  # (código del equipo, código de enrolamiento en claro)


def nombre_sala(n: int) -> str:
    return f"Sala Dev {n}"


def codigo_equipo(sala: int, equipo: int) -> str:
    return f"DEV-S{sala}-PC{equipo:02d}"


def generar_codigo_enrolamiento() -> str:
    """Código de un solo uso con 128 bits de azar."""
    return secrets.token_urlsafe(16)


def validar_entorno(app_env: str) -> None:
    if app_env != "dev":
        raise ValueError("La semilla de dev solo corre con APP_ENV=dev.")


async def sembrar(
    db: AsyncSession,
    *,
    admin_email: str,
    admin_password: str,
    blind_index_key: str,
    salas: int = 1,
    equipos_por_sala: int = 3,
    codigos: int = 0,
    vigencia_horas: int = 24,
) -> Resumen:
    """Deja la base con los datos de dev. No hace commit: lo decide quien llama."""
    # Importaciones locales: app.config exige variables de entorno al importarse
    from app.audit import audit
    from app.crypto import compute_blind_index, sha256_digest
    from app.models import (
        AuditActorType,
        EnrollmentCode,
        Lab,
        Machine,
        MachineStatus,
        User,
        UserRole,
        UserStatus,
    )
    from app.services.passwords import hash_password

    if not 0 <= codigos <= MAX_CODIGOS:
        raise ValueError(f"Se pueden pedir entre 0 y {MAX_CODIGOS} códigos.")
    ahora = datetime.now(UTC)

    # Administrador: se busca por índice ciego; si existe, se reafirma rol, estado y contraseña.
    # La interfaz `pii` real llega con SEC-06; hasta entonces los *_ct van en claro, igual
    # que en las fixtures de integración, y `reset` vuelve a sembrar cuando cambie.
    email_bidx = compute_blind_index(admin_email, blind_index_key)
    admin = await db.scalar(select(User).where(User.email_bidx == email_bidx))
    admin_creado = admin is None
    if admin is None:
        admin = User(
            email_ct=admin_email.strip().lower().encode(),
            email_bidx=email_bidx,
            full_name_ct=ADMIN_NOMBRE.encode(),
            privacy_consent_at=ahora,
        )
        db.add(admin)
    admin.password_hash = hash_password(admin_password)
    admin.role = UserRole.admin
    admin.status = UserStatus.active
    admin.email_verified_at = admin.email_verified_at or ahora
    await db.flush()

    salas_creadas = equipos_creados = 0
    equipos_pendientes: list[Machine] = []
    for s in range(1, salas + 1):
        lab = await db.scalar(select(Lab).where(Lab.name == nombre_sala(s)))
        if lab is None:
            lab = Lab(name=nombre_sala(s), building=EDIFICIO_DEV)
            db.add(lab)
            await db.flush()
            salas_creadas += 1
        for e in range(1, equipos_por_sala + 1):
            maquina = await db.scalar(select(Machine).where(Machine.code == codigo_equipo(s, e)))
            if maquina is None:
                maquina = Machine(code=codigo_equipo(s, e), lab_id=lab.id)
                db.add(maquina)
                await db.flush()
                equipos_creados += 1
            if maquina.status == MachineStatus.pending_enrollment:
                equipos_pendientes.append(maquina)

    generados: list[tuple[str, str]] = []
    if codigos:
        if not equipos_pendientes:
            raise ValueError("No hay equipos pendientes de enrolar para asignar códigos.")
        for i in range(codigos):
            maquina = equipos_pendientes[i % len(equipos_pendientes)]
            codigo = generar_codigo_enrolamiento()
            db.add(
                EnrollmentCode(
                    machine_id=maquina.id,
                    code_hash=sha256_digest(codigo),
                    created_by=admin.id,
                    expires_at=ahora + timedelta(hours=vigencia_horas),
                )
            )
            generados.append((maquina.code, codigo))

    await audit(
        db,
        AuditActorType.system,
        "seed.dev",
        metadata_info={
            "admin_creado": admin_creado,
            "salas_creadas": salas_creadas,
            "equipos_creados": equipos_creados,
            "codigos": len(generados),
        },
    )
    await db.flush()
    return Resumen(admin_creado, salas_creadas, equipos_creados, generados)


async def _ejecutar(args: argparse.Namespace, admin_email: str, admin_password: str) -> Resumen:
    from app.config import settings
    from app.database import SesionLocalAsync, motor_async

    if not settings.blind_index_key:
        raise ValueError("Define BLIND_INDEX_KEY (la misma de la API de dev).")
    try:
        async with SesionLocalAsync() as db:
            resumen = await sembrar(
                db,
                admin_email=admin_email,
                admin_password=admin_password,
                blind_index_key=settings.blind_index_key,
                salas=args.salas,
                equipos_por_sala=args.equipos_por_sala,
                codigos=args.codigos,
                vigencia_horas=args.vigencia_horas,
            )
            await db.commit()
    finally:
        await motor_async.dispose()
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semilla idempotente del entorno dev.")
    parser.add_argument("--salas", type=int, default=1)
    parser.add_argument("--equipos-por-sala", type=int, default=3)
    parser.add_argument("--codigos", type=int, default=0, help=f"Códigos de enrolamiento (0 a {MAX_CODIGOS}).")
    parser.add_argument("--vigencia-horas", type=int, default=24)
    parser.add_argument("--salida-codigos", type=Path, help="Archivo donde escribir los códigos en claro.")
    args = parser.parse_args(argv)

    try:
        validar_entorno(os.environ.get("APP_ENV", ""))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD")
    if not admin_password:
        print("ERROR: define SEED_ADMIN_PASSWORD en el entorno.", file=sys.stderr)
        return 2
    if args.codigos and not args.salida_codigos:
        print("ERROR: con --codigos hay que indicar --salida-codigos.", file=sys.stderr)
        return 2
    admin_email = os.environ.get("SEED_ADMIN_EMAIL") or ADMIN_EMAIL_POR_DEFECTO

    try:
        resumen = asyncio.run(_ejecutar(args, admin_email, admin_password))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if resumen.codigos:
        lineas = [f"{equipo}\t{codigo}" for equipo, codigo in resumen.codigos]
        args.salida_codigos.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(
        f"Semilla aplicada: administrador {'creado' if resumen.admin_creado else 'actualizado'}, "
        f"{resumen.salas_creadas} salas nuevas, {resumen.equipos_creados} equipos nuevos, "
        f"{len(resumen.codigos)} códigos de enrolamiento."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
