"""Tarea periódica de inactividad (BE-09b, RN-07, SRS §8.9).

Cada ``INACTIVIDAD_INTERVALO_S`` segundos (30 por defecto) cierra las sesiones
sin latido durante ``HEARTBEAT_TIMEOUT_S`` (3 min) con ``ended_at =
last_heartbeat_at`` y marca como ``expired`` los retos QR vencidos.

Para no despertar la base de Neon sin necesidad, el ciclo solo consulta la base
si hubo **actividad en memoria**: una confirmación de QR o un latido con sesión.
Como esa marca se pierde al reiniciar, al arrancar se hace un barrido completo
de la base. ``barrer`` es invocable desde las pruebas con la hora controlada.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.logger import obtener_logger
from app.models import AccessSession, ChallengeStatus, LoginChallenge
from app.services.challenges import ahora
from app.services.sesiones import cerrar_sesiones_inactivas

logger = obtener_logger("inactividad")

_hay_actividad = False


@dataclass(frozen=True)
class ResultadoBarrido:
    """Lo que hizo un barrido."""

    sesiones_cerradas: int
    retos_expirados: int
    sesiones_abiertas: int


def marcar_actividad() -> None:
    """Avisa a la tarea que hay sesiones vivas que vigilar.

    La llaman ``POST /scan/claim`` y ``POST /machine/heartbeat``.
    """
    global _hay_actividad
    _hay_actividad = True


def hay_actividad() -> bool:
    """Indica si el próximo ciclo debe consultar la base.

    Returns:
        ``True`` si hubo actividad desde el último barrido sin sesiones abiertas.
    """
    return _hay_actividad


def reiniciar() -> None:
    """Olvida la actividad en memoria (solo para las pruebas)."""
    global _hay_actividad
    _hay_actividad = False


async def barrer(db: AsyncSession, now: datetime | None = None) -> ResultadoBarrido:
    """Cierra las sesiones inactivas, expira los retos vencidos y confirma.

    Si después del barrido no queda ninguna sesión abierta, se apaga la marca
    de actividad: los ciclos siguientes no tocan la base hasta un nuevo claim
    o latido.

    Args:
        db: Sesión de base de datos.
        now: Hora actual; solo para las pruebas.

    Returns:
        Cuántas sesiones se cerraron, cuántos retos expiraron y cuántas
        sesiones siguen abiertas.
    """
    global _hay_actividad
    now = now or ahora()
    cerradas = await cerrar_sesiones_inactivas(db, now=now)
    expirados = await db.execute(
        update(LoginChallenge)
        .where(LoginChallenge.status == ChallengeStatus.pending, LoginChallenge.expires_at <= now)
        .values(status=ChallengeStatus.expired)
        .execution_options(synchronize_session=False)
    )
    abiertas = await db.scalar(
        select(func.count()).select_from(AccessSession).where(AccessSession.ended_at.is_(None))
    )
    await db.commit()
    _hay_actividad = bool(abiertas)
    resultado = ResultadoBarrido(cerradas, expirados.rowcount or 0, abiertas or 0)
    if resultado.sesiones_cerradas or resultado.retos_expirados:
        logger.info(
            "Barrido de inactividad",
            extra={"datos": {
                "evento": "inactividad.barrido",
                "sesiones_cerradas": resultado.sesiones_cerradas,
                "retos_expirados": resultado.retos_expirados,
            }},
        )
    return resultado


async def ciclo(fabrica: async_sessionmaker) -> ResultadoBarrido | None:
    """Ejecuta un ciclo: barre solo si hubo actividad.

    Args:
        fabrica: Fábrica de sesiones de base de datos.

    Returns:
        El resultado del barrido, o ``None`` si no hubo actividad.
    """
    if not _hay_actividad:
        return None
    async with fabrica() as db:
        return await barrer(db)


async def barrido_inicial(fabrica: async_sessionmaker) -> None:
    """Barrido completo al arrancar; un fallo de la base no impide el arranque.

    Args:
        fabrica: Fábrica de sesiones de base de datos.
    """
    try:
        async with fabrica() as db:
            await barrer(db)
    except Exception as exc:  # la base puede no estar lista; /readyz lo refleja
        marcar_actividad()  # se reintenta en el primer ciclo
        logger.warning(
            "No se pudo hacer el barrido inicial",
            extra={"datos": {"evento": "inactividad.barrido_inicial_fallo",
                             "excepcion": type(exc).__name__}},
        )


async def tarea_periodica(fabrica: async_sessionmaker, intervalo_s: float | None = None) -> None:
    """Bucle de la tarea: un ciclo cada ``intervalo_s`` hasta que la cancelen.

    Un error en un ciclo se registra y no detiene la tarea.

    Args:
        fabrica: Fábrica de sesiones de base de datos.
        intervalo_s: Segundos entre ciclos; por defecto ``INACTIVIDAD_INTERVALO_S``.
    """
    intervalo = intervalo_s or settings.inactividad_intervalo_s
    while True:
        await asyncio.sleep(intervalo)
        try:
            await ciclo(fabrica)
        except Exception as exc:
            logger.error(
                "Falló un ciclo de inactividad",
                extra={"datos": {"evento": "inactividad.fallo", "excepcion": type(exc).__name__}},
            )
