"""Prepara las identidades de los equipos sintéticos para la carga en dev."""

import asyncio
import json
import os
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tools.seed_dev import EDIFICIO_DEV, validar_entorno

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "contracts" / "test-vectors"))
import firmador_referencia as firmador  # noqa: E402

TOTAL_EQUIPOS = 300
ARCHIVO_CLAVES = Path(".env.locust.json")
SALA = "Sala Dev Locust"
LATIDO = "/api/v1/machine/heartbeat"
RETO_EN_ESPERA = "/api/v1/machine/challenges/wait"
CUERPO_LATIDO = b"{}"


def leer_claves(archivo: Path) -> list[ec.EllipticCurvePrivateKey]:
    """Lee las 300 claves privadas P-256 locales, una por equipo."""
    valores = json.loads(archivo.read_text(encoding="utf-8"))
    if not isinstance(valores, list) or len(valores) != TOTAL_EQUIPOS:
        raise ValueError("Cantidad de claves inválida.")
    if any(not isinstance(valor, str) or len(valor) != 43 for valor in valores):
        raise ValueError("Formato de clave P-256 inválido.")
    escalares = [int.from_bytes(firmador.b64url_dec(valor), "big") for valor in valores]
    if len(set(escalares)) != TOTAL_EQUIPOS or any(not 0 < d < firmador.ORDEN for d in escalares):
        raise ValueError("Se requieren claves P-256 distintas y válidas.")
    return [ec.derive_private_key(d, ec.SECP256R1()) for d in escalares]


def cargar_o_crear_claves(archivo: Path) -> list[ec.EllipticCurvePrivateKey]:
    """Conserva las claves entre ejecuciones y crea el archivo con permisos privados en POSIX."""
    try:
        return leer_claves(archivo)
    except FileNotFoundError:
        claves = [ec.generate_private_key(ec.SECP256R1()) for _ in range(TOTAL_EQUIPOS)]
        contenido = json.dumps([firmador.jwk_privada(clave)["d"] for clave in claves])
        try:
            fd = os.open(archivo, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return leer_claves(archivo)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as salida:
                salida.write(contenido)
        except OSError:
            archivo.unlink(missing_ok=True)
            raise
        return claves


def cabeceras_firmadas(
    clave: ec.EllipticCurvePrivateKey, metodo: str, uri: str, cuerpo: bytes | None = None
) -> dict[str, str]:
    """Firma la URL completa y los mismos bytes que se enviarán a la API."""
    peticion = firmador.Peticion(metodo, uri, cuerpo)
    firma = firmador.firmar_peticion(clave, peticion, int(time.time()), secrets.token_urlsafe(16))
    cabeceras = {
        "Signature-Input": firma["signature_input"],
        "Signature": f"{firmador.ETIQUETA}=:{firma['firma']}:",
    }
    if cuerpo:
        cabeceras["Content-Type"] = "application/json"
        cabeceras["Content-Digest"] = firmador.content_digest(cuerpo)
    return cabeceras


async def sembrar_equipos(
    sesiones: async_sessionmaker[AsyncSession], claves: list[ec.EllipticCurvePrivateKey]
) -> None:
    """Registra las claves públicas en una sola transacción y verifica las filas existentes."""
    from app.models import Lab, Machine, MachineStatus

    ahora = datetime.now(UTC)
    registros = {}
    for numero, clave in enumerate(claves, start=1):
        jwk = firmador.jwk_publica(clave)
        codigo = f"DEV-LOCUST-PC{numero:03d}"
        registros[codigo] = {
            "code": codigo,
            "status": MachineStatus.active,
            "public_key_jwk": jwk,
            "key_thumbprint": firmador.huella_rfc7638(jwk),
            "enrolled_at": ahora,
        }

    async with sesiones.begin() as db:
        sala = insert(Lab).values(name=SALA, building=EDIFICIO_DEV)
        await db.execute(sala.on_conflict_do_nothing(index_elements=[Lab.name]))
        sala_id = await db.scalar(select(Lab.id).where(Lab.name == SALA))
        equipos = insert(Machine).values([{**registro, "lab_id": sala_id} for registro in registros.values()])
        await db.execute(equipos.on_conflict_do_nothing(index_elements=[Machine.code]))
        for equipo in await db.scalars(select(Machine).where(Machine.code.in_(list(registros)))):
            registro = registros[equipo.code]
            if (
                equipo.lab_id != sala_id
                or equipo.status != MachineStatus.active
                or equipo.key_thumbprint != registro["key_thumbprint"]
                or equipo.public_key_jwk != registro["public_key_jwk"]
            ):
                raise ValueError("Hay equipos de carga con un estado o una clave distintos.")


async def _preparar(claves: list[ec.EllipticCurvePrivateKey]) -> None:
    from app.database import SesionLocalAsync, motor_async

    try:
        await sembrar_equipos(SesionLocalAsync, claves)
    finally:
        await motor_async.dispose()


def main() -> int:
    """Prepara los datos de dev sin escribir credenciales en la salida."""
    try:
        validar_entorno(os.getenv("APP_ENV", ""))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    try:
        claves = cargar_o_crear_claves(ARCHIVO_CLAVES)
    except (OSError, ValueError):
        print("No se pudo cargar o crear .env.locust.json.", file=sys.stderr)
        return 1

    try:
        asyncio.run(_preparar(claves))
    except Exception as error:
        # Las excepciones de configuración o conexión pueden contener valores sensibles.
        print(f"No se pudieron preparar los equipos de dev ({type(error).__name__}).", file=sys.stderr)
        return 1

    print(f"{TOTAL_EQUIPOS} equipos sintéticos listos para Locust.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
