"""Lógica de negocio para los endpoints del portal del estudiante (BE-11).

Este módulo centraliza las consultas y operaciones relacionadas con el perfil
y las sesiones de acceso del estudiante autenticado. Ninguna función del
servicio devuelve datos personales en claro hacia la capa de presentación;
el router es responsable de formatear la respuesta final.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessSession, Lab, Machine, SessionEndReason, User


# ---------------------------------------------------------------------------
# Excepciones propias del dominio del estudiante
# ---------------------------------------------------------------------------

class SesionNoEncontradaError(Exception):
    """La sesión solicitada no existe o no pertenece al usuario."""


class SesionYaTerminadaError(Exception):
    """La sesión ya fue cerrada antes; no se puede cerrar de nuevo."""


class SesionDeOtroUsuarioError(Exception):
    """El estudiante intentó operar sobre una sesión que no es suya."""


# ---------------------------------------------------------------------------
# Consultas de perfil
# ---------------------------------------------------------------------------

async def obtener_perfil(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Recupera la fila del usuario a partir de su UUID.

    Args:
        db: Sesión de base de datos asíncrona.
        user_id: UUID del usuario autenticado.

    Returns:
        Instancia del modelo User.

    Raises:
        SesionNoEncontradaError: Si el usuario no existe (caso raro; el token
            ya fue validado, pero la cuenta podría haber sido eliminada).
    """
    resultado = await db.execute(select(User).where(User.id == user_id))
    usuario = resultado.scalar_one_or_none()
    if usuario is None:
        # Esto no debería pasar si el token es válido, pero lo cubrimos igual
        raise SesionNoEncontradaError("Usuario no encontrado.")
    return usuario


# ---------------------------------------------------------------------------
# Consultas de sesiones
# ---------------------------------------------------------------------------

async def obtener_sesion_activa(
    db: AsyncSession, user_id: uuid.UUID
) -> AccessSession | None:
    """Busca la sesión de acceso activa del estudiante (sin ended_at).

    Args:
        db: Sesión de base de datos asíncrona.
        user_id: UUID del usuario.

    Returns:
        La AccessSession activa, o None si no hay ninguna en curso.
    """
    resultado = await db.execute(
        select(AccessSession).where(
            AccessSession.user_id == user_id,
            AccessSession.ended_at.is_(None),
        )
    )
    return resultado.scalar_one_or_none()


async def obtener_sesiones_paginadas(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[AccessSession, Machine, Lab | None]], int]:
    """Devuelve el historial de sesiones del estudiante, con datos de la máquina.

    Las sesiones se ordenan de más reciente a más antigua. Se incluyen tanto
    sesiones terminadas como la activa (si existe).

    Args:
        db: Sesión de base de datos asíncrona.
        user_id: UUID del usuario.
        page: Número de página (empieza en 1).
        page_size: Cantidad de registros por página (máximo 100).

    Returns:
        Tupla con:
        - Lista de tuplas (AccessSession, Machine, Lab | None).
        - Total de registros encontrados (para calcular páginas en el frontend).
    """
    # Sanitizamos los parámetros para evitar páginas vacías o enormes
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    # Consulta base: join con Machine y opcionalmente con Lab
    base_query = (
        select(AccessSession, Machine, Lab)
        .join(Machine, AccessSession.machine_id == Machine.id)
        .outerjoin(Lab, Machine.lab_id == Lab.id)
        .where(AccessSession.user_id == user_id)
        .order_by(AccessSession.started_at.desc())
    )

    # Conteo total para la paginación
    count_query = select(AccessSession.id).where(AccessSession.user_id == user_id)
    total_result = await db.execute(count_query)
    total = len(total_result.all())

    # Aplicamos offset y limit
    offset = (page - 1) * page_size
    paginated_query = base_query.offset(offset).limit(page_size)
    resultado = await db.execute(paginated_query)
    filas = resultado.all()  # Lista de Row(AccessSession, Machine, Lab)

    return filas, total


# ---------------------------------------------------------------------------
# Operaciones sobre sesiones
# ---------------------------------------------------------------------------

async def cerrar_sesion(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AccessSession:
    """Cierra la sesión de acceso identificada por session_id.

    Verifica que la sesión exista, pertenezca al usuario y no esté ya cerrada.
    Si todo está bien, registra el timestamp de cierre y la razón 'user_logout_web'.

    Args:
        db: Sesión de base de datos asíncrona.
        session_id: UUID de la sesión a cerrar.
        user_id: UUID del usuario que hace la solicitud.

    Returns:
        La AccessSession actualizada.

    Raises:
        SesionNoEncontradaError: Si la sesión no existe.
        SesionDeOtroUsuarioError: Si la sesión no pertenece al usuario.
        SesionYaTerminadaError: Si la sesión ya fue cerrada antes.
    """
    resultado = await db.execute(
        select(AccessSession).where(AccessSession.id == session_id)
    )
    sesion = resultado.scalar_one_or_none()

    if sesion is None:
        raise SesionNoEncontradaError(f"Sesión {session_id} no encontrada.")

    # Verificamos que la sesión pertenezca a quien está pidiendo el cierre
    if sesion.user_id != user_id:
        raise SesionDeOtroUsuarioError("No tienes permiso para cerrar esta sesión.")

    # Si ya tiene ended_at, significa que ya fue cerrada (por cualquier razón)
    if sesion.ended_at is not None:
        raise SesionYaTerminadaError("La sesión ya estaba cerrada.")

    # Marcamos el cierre con la razón correspondiente al portal web
    sesion.ended_at = datetime.now(timezone.utc)
    sesion.end_reason = SessionEndReason.user_logout_web

    await db.commit()
    await db.refresh(sesion)
    return sesion
