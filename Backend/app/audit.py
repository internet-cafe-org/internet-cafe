"""Módulo de auditoría para el sistema (SRS Sección 11.2).

Proporciona la función helper audit() para registrar acciones en la base de datos
sin acoplar esta lógica a los modelos ORM.
"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog, AuditActorType

async def audit(
    db: AsyncSession, 
    actor_type: AuditActorType, 
    action: str, 
    actor_id: uuid.UUID = None, 
    target_type: str = None, 
    target_id: uuid.UUID = None, 
    metadata_info: dict = None
):
    """Agrega una entrada al log de auditoría; no hace commit.

    Args:
        db: Sesión de base de datos.
        actor_type: Quién actúa: usuario, equipo o sistema.
        action: Nombre de la acción (p. ej. ``auth.login``).
        actor_id: Id del actor, si lo tiene.
        target_type: Tipo del objeto afectado.
        target_id: Id del objeto afectado.
        metadata_info: Datos extra, nunca personales ni secretos.
    """
    log_entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_info=metadata_info
    )
    db.add(log_entry)