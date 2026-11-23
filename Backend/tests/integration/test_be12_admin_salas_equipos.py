"""Pruebas de integración para BE-12: admin de salas y equipos (HU-14).

Verifica el camino feliz de los endpoints de administración de salas y equipos
contra la API real (/api/v1/admin) con una base de datos PostgreSQL de pruebas.

Cobertura específica de BE-12:
- Crear sala → 201 con los campos del contrato, auditoría registrada.
- Listar salas → orden alfabético, paginación, total correcto.
- Nombre de sala duplicado → 409 CONFLICT.
- Listar equipos → filtros por sala y estado, paginación, sin claves ni secretos.
- Editar equipo: cambiar sala → 200, auditoría con los campos modificados.
- Cambiar modo → passive/kiosk, auditado.
- Deshabilitar equipo (RN-08) → cancela retos pendientes, cierra sesión con
  `admin_forced` y registra auditoría.
- Activar equipo sin enrolar → 409 CONFLICT.

Requisito de base de datos: TEST_DATABASE_URL con "test" en el nombre.
Si no está definida, todas las pruebas se saltan automáticamente.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import (
    AccessSession,
    AuditLog,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineStatus,
    SessionEndReason,
    User,
    UserRole,
    UserStatus,
)

API = "/api/v1"


# ------------------------------------------------------------------ fixtures


def _par_de_claves() -> tuple[str, str]:
    """Par ES256 efímero (privada, pública) en PEM para los tests."""
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    publica = (
        clave.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return privada, publica


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> str:
    """Sustituye las claves JWT de settings por un par efímero y devuelve la privada."""
    privada, publica = _par_de_claves()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    return privada


@pytest.fixture
async def cliente(
    sesiones: async_sessionmaker[AsyncSession], claves: str
) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP que apunta a la app con la BD de pruebas inyectada."""

    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Administrador activo con datos de prueba (no hay datos reales)."""
    usuario = User(
        email_ct=b"admin-be12@test.invalid",
        email_bidx=uuid.uuid4().bytes,
        full_name_ct=b"Admin BE-12",
        password_hash="no-es-un-hash",
        role=UserRole.admin,
        status=UserStatus.active,
        privacy_consent_at=datetime.now(UTC),
    )
    async with sesiones() as db:
        db.add(usuario)
        await db.commit()
    return usuario


def _cab_admin(claves: str, admin: User) -> dict[str, str]:
    """Cabeceras Authorization con el token del administrador."""
    token = create_access_token(subject=str(admin.id), role=admin.role.value, private_key=claves)
    return {"Authorization": f"Bearer {token}"}


async def _contar_auditorias(
    sesiones: async_sessionmaker[AsyncSession], accion: str
) -> int:
    async with sesiones() as db:
        return (
            await db.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == accion)
            )
        ).scalar_one()


async def _crear_sala(sesiones: async_sessionmaker[AsyncSession], nombre: str) -> Lab:
    async with sesiones() as db:
        sala = Lab(name=nombre)
        db.add(sala)
        await db.commit()
        return sala


async def _crear_equipo(
    sesiones: async_sessionmaker[AsyncSession],
    codigo: str,
    *,
    lab_id: uuid.UUID | None = None,
    status: MachineStatus = MachineStatus.active,
    enrolado: bool = True,
) -> Machine:
    async with sesiones() as db:
        maq = Machine(
            code=codigo,
            lab_id=lab_id,
            status=status,
            enrolled_at=datetime.now(UTC) if enrolado else None,
        )
        db.add(maq)
        await db.commit()
        return maq


async def _crear_sesion_abierta(
    sesiones: async_sessionmaker[AsyncSession], equipo: Machine, usuario: User
) -> uuid.UUID:
    """Inserta un reto aprobado y la sesión activa que origina."""
    inicio = datetime.now(UTC) - timedelta(minutes=10)
    async with sesiones() as db:
        reto = LoginChallenge(
            machine_id=equipo.id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.approved,
            approved_by=usuario.id,
            approved_at=inicio,
            expires_at=inicio + timedelta(seconds=60),
        )
        db.add(reto)
        await db.flush()
        sesion = AccessSession(
            user_id=usuario.id,
            machine_id=equipo.id,
            challenge_id=reto.id,
            started_at=inicio,
            last_heartbeat_at=inicio,
        )
        db.add(sesion)
        await db.commit()
        return sesion.id


async def _crear_reto_pendiente(
    sesiones: async_sessionmaker[AsyncSession], equipo: Machine
) -> uuid.UUID:
    async with sesiones() as db:
        reto = LoginChallenge(
            machine_id=equipo.id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.pending,
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        db.add(reto)
        await db.commit()
        return reto.id


async def _estudiante(sesiones: async_sessionmaker[AsyncSession]) -> User:
    async with sesiones() as db:
        u = User(
            email_ct=b"stu-be12@test.invalid",
            email_bidx=uuid.uuid4().bytes,
            full_name_ct=b"Estudiante BE-12",
            student_code_ct=b"20211099901",
            student_code_bidx=uuid.uuid4().bytes,
            password_hash="no-es-un-hash",
            role=UserRole.student,
            status=UserStatus.active,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(u)
        await db.commit()
        return u


# ------------------------------------------------------------------ salas


async def test_crear_sala_devuelve_201_con_los_campos_del_contrato(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """POST /admin/labs crea la sala y devuelve id, name y building."""
    cab = _cab_admin(claves, admin)
    resp = await cliente.post(f"{API}/admin/labs", json={"name": "Sala A", "building": "Bloque 2"}, headers=cab)

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Sala A"
    assert body["building"] == "Bloque 2"
    assert uuid.UUID(body["id"])  # es un UUID válido


async def test_crear_sala_registra_auditoria(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Crear una sala deja una entrada 'lab_created' en audit_log."""
    antes = await _contar_auditorias(sesiones, "lab_created")
    cab = _cab_admin(claves, admin)

    await cliente.post(f"{API}/admin/labs", json={"name": "Sala Auditada"}, headers=cab)

    despues = await _contar_auditorias(sesiones, "lab_created")
    assert despues == antes + 1


async def test_nombre_de_sala_duplicado_devuelve_409(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Crear una sala con nombre repetido devuelve 409 CONFLICT."""
    await _crear_sala(sesiones, "Sala Duplicada")
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(f"{API}/admin/labs", json={"name": "Sala Duplicada"}, headers=cab)

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"


async def test_listar_salas_orden_alfabetico_y_paginacion(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """GET /admin/labs devuelve las salas en orden alfabético con total correcto."""
    for nombre in ("Zeta", "Alpha", "Mu"):
        await _crear_sala(sesiones, nombre)
    cab = _cab_admin(claves, admin)

    resp = await cliente.get(f"{API}/admin/labs?limit=10&offset=0", headers=cab)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    nombres = [item["name"] for item in body["items"]]
    assert nombres == sorted(nombres)  # orden alfabético


async def test_listar_salas_paginacion_limit_offset(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Paginación: limit=1 devuelve exactamente 1 sala pero total es el real."""
    for nombre in ("P-Sala-1", "P-Sala-2", "P-Sala-3"):
        await _crear_sala(sesiones, nombre)
    cab = _cab_admin(claves, admin)

    resp = await cliente.get(f"{API}/admin/labs?limit=1&offset=0", headers=cab)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 3
    assert body["limit"] == 1
    assert body["offset"] == 0


# ------------------------------------------------------------------ equipos


async def test_listar_equipos_devuelve_pagina_con_total(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """GET /admin/machines devuelve todos los campos del contrato sin secretos."""
    sala = await _crear_sala(sesiones, "Sala Equipos")
    await _crear_equipo(sesiones, "BE12-PC01", lab_id=sala.id)
    cab = _cab_admin(claves, admin)

    resp = await cliente.get(f"{API}/admin/machines", headers=cab)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    equipo = next((e for e in body["items"] if e["code"] == "BE12-PC01"), None)
    assert equipo is not None
    # Nunca deben aparecer secretos en la respuesta
    assert "credential_hash" not in equipo
    assert "public_key_jwk" not in equipo


async def test_listar_equipos_filtra_por_sala(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Filtrar por lab_id devuelve solo los equipos de esa sala."""
    sala = await _crear_sala(sesiones, "Sala Filtro")
    await _crear_equipo(sesiones, "BE12-FILT-01", lab_id=sala.id)
    await _crear_equipo(sesiones, "BE12-FILT-OTRO")  # sin sala
    cab = _cab_admin(claves, admin)

    resp = await cliente.get(f"{API}/admin/machines?lab_id={sala.id}", headers=cab)

    assert resp.status_code == 200
    codigos = [e["code"] for e in resp.json()["items"]]
    assert "BE12-FILT-01" in codigos
    assert "BE12-FILT-OTRO" not in codigos


async def test_listar_equipos_filtra_por_estado(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Filtrar por status=disabled devuelve solo los equipos deshabilitados."""
    await _crear_equipo(sesiones, "BE12-DIS-01", status=MachineStatus.disabled)
    await _crear_equipo(sesiones, "BE12-ACT-01", status=MachineStatus.active)
    cab = _cab_admin(claves, admin)

    resp = await cliente.get(f"{API}/admin/machines?status=disabled", headers=cab)

    assert resp.status_code == 200
    codigos = [e["code"] for e in resp.json()["items"]]
    assert "BE12-DIS-01" in codigos
    assert "BE12-ACT-01" not in codigos


async def test_editar_equipo_cambiar_sala(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """PATCH /admin/machines/{id} con lab_id cambia la sala y audita el cambio."""
    sala = await _crear_sala(sesiones, "Sala Destino BE12")
    equipo = await _crear_equipo(sesiones, "BE12-EDIT-01")
    antes = await _contar_auditorias(sesiones, "machine_updated")
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"lab_id": str(sala.id)},
        headers=cab,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["lab_id"] == str(sala.id)
    assert body["lab"] == "Sala Destino BE12"
    despues = await _contar_auditorias(sesiones, "machine_updated")
    assert despues == antes + 1


async def test_editar_equipo_cambiar_modo(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """PATCH con mode=kiosk cambia el modo y lo devuelve en la respuesta."""
    equipo = await _crear_equipo(sesiones, "BE12-MODO-01")
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"mode": "kiosk"},
        headers=cab,
    )

    assert resp.status_code == 200
    assert resp.json()["mode"] == "kiosk"


async def test_deshabilitar_equipo_cancela_retos_y_cierra_sesion(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Deshabilitar (RN-08): cancela retos pending y cierra la sesión con admin_forced."""
    estudiante = await _estudiante(sesiones)
    equipo = await _crear_equipo(sesiones, "BE12-DIS-RN08")
    reto_id = await _crear_reto_pendiente(sesiones, equipo)
    sesion_id = await _crear_sesion_abierta(sesiones, equipo, estudiante)
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"status": "disabled"},
        headers=cab,
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"

    # El reto debe quedar cancelado
    async with sesiones() as db:
        reto = (
            await db.execute(select(LoginChallenge).where(LoginChallenge.id == reto_id))
        ).scalar_one()
        assert reto.status == ChallengeStatus.cancelled

    # La sesión debe quedar cerrada con motivo admin_forced
    async with sesiones() as db:
        sesion = (
            await db.execute(select(AccessSession).where(AccessSession.id == sesion_id))
        ).scalar_one()
        assert sesion.ended_at is not None
        assert sesion.end_reason == SessionEndReason.admin_forced


async def test_deshabilitar_equipo_registra_auditoria(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Deshabilitar un equipo con sesión abierta deja auditoría del cierre forzado."""
    estudiante = await _estudiante(sesiones)
    equipo = await _crear_equipo(sesiones, "BE12-DIS-AUDIT")
    await _crear_sesion_abierta(sesiones, equipo, estudiante)
    antes = await _contar_auditorias(sesiones, "session_ended")
    cab = _cab_admin(claves, admin)

    await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"status": "disabled"},
        headers=cab,
    )

    despues = await _contar_auditorias(sesiones, "session_ended")
    assert despues == antes + 1


async def test_activar_equipo_sin_enrolar_devuelve_409(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Activar un equipo que no se ha enrolado devuelve 409 CONFLICT."""
    equipo = await _crear_equipo(
        sesiones, "BE12-NOENROL", status=MachineStatus.pending_enrollment, enrolado=False
    )
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"status": "active"},
        headers=cab,
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"


async def test_editar_equipo_inexistente_devuelve_404(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """PATCH de un equipo que no existe devuelve 404 NOT_FOUND."""
    id_falso = "00000000-0000-4000-8000-000000000099"
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/machines/{id_falso}",
        json={"mode": "passive"},
        headers=cab,
    )

    assert resp.status_code == 404


async def test_respuesta_equipos_nunca_incluye_secretos(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Los campos sensibles (credential_hash, public_key_jwk) no salen en ninguna respuesta."""
    sala = await _crear_sala(sesiones, "Sala Secretos")
    equipo = await _crear_equipo(sesiones, "BE12-SEC-01", lab_id=sala.id)
    cab = _cab_admin(claves, admin)

    # Lista
    resp_lista = await cliente.get(f"{API}/admin/machines", headers=cab)
    for item in resp_lista.json()["items"]:
        assert "credential_hash" not in item
        assert "public_key_jwk" not in item
        assert "key_thumbprint" not in item

    # Edición
    resp_patch = await cliente.patch(
        f"{API}/admin/machines/{equipo.id}",
        json={"mode": "kiosk"},
        headers=cab,
    )
    for campo in ("credential_hash", "public_key_jwk", "key_thumbprint"):
        assert campo not in resp_patch.json()


# ------------------------------------------------------------------ editar sala

async def test_editar_sala_cambia_nombre_y_devuelve_200(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """PATCH /admin/labs/{id} actualiza el nombre y lo devuelve en la respuesta."""
    sala = await _crear_sala(sesiones, "Sala Original")
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/labs/{sala.id}",
        json={"name": "Sala Renombrada"},
        headers=cab,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Sala Renombrada"
    assert body["id"] == str(sala.id)


async def test_editar_sala_registra_auditoria(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Editar una sala deja una entrada 'lab_updated' en audit_log."""
    sala = await _crear_sala(sesiones, "Sala Audit Edit")
    antes = await _contar_auditorias(sesiones, "lab_updated")
    cab = _cab_admin(claves, admin)

    await cliente.patch(
        f"{API}/admin/labs/{sala.id}",
        json={"building": "Bloque Nuevo"},
        headers=cab,
    )

    despues = await _contar_auditorias(sesiones, "lab_updated")
    assert despues == antes + 1


async def test_editar_sala_nombre_duplicado_devuelve_409(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Renombrar una sala con un nombre ya usado por otra devuelve 409 CONFLICT."""
    await _crear_sala(sesiones, "Sala Ocupada")
    sala = await _crear_sala(sesiones, "Sala Libre")
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/labs/{sala.id}",
        json={"name": "Sala Ocupada"},
        headers=cab,
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"


async def test_editar_sala_inexistente_devuelve_404(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """PATCH de una sala que no existe devuelve 404 NOT_FOUND."""
    id_falso = "00000000-0000-4000-8000-000000000098"
    cab = _cab_admin(claves, admin)

    resp = await cliente.patch(
        f"{API}/admin/labs/{id_falso}",
        json={"name": "No importa"},
        headers=cab,
    )

    assert resp.status_code == 404


# ------------------------------------------------------------------ crear equipo


async def test_crear_equipo_devuelve_201_en_pending_enrollment(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """POST /admin/machines crea el equipo en estado pending_enrollment."""
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-NEW-PC01"},
        headers=cab,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == "BE12-NEW-PC01"
    assert body["status"] == "pending_enrollment"
    assert uuid.UUID(body["id"])


async def test_crear_equipo_con_sala_y_modo(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """POST /admin/machines acepta lab_id y mode en el cuerpo."""
    sala = await _crear_sala(sesiones, "Sala Nuevo Equipo")
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-NEW-PC02", "lab_id": str(sala.id), "mode": "kiosk"},
        headers=cab,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["lab_id"] == str(sala.id)
    assert body["mode"] == "kiosk"
    assert body["lab"] == "Sala Nuevo Equipo"


async def test_crear_equipo_registra_auditoria(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Crear un equipo deja una entrada 'machine_created' en audit_log."""
    antes = await _contar_auditorias(sesiones, "machine_created")
    cab = _cab_admin(claves, admin)

    await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-AUDIT-NEW"},
        headers=cab,
    )

    despues = await _contar_auditorias(sesiones, "machine_created")
    assert despues == antes + 1


async def test_crear_equipo_codigo_duplicado_devuelve_409(
    cliente: AsyncClient,
    sesiones: async_sessionmaker[AsyncSession],
    claves: str,
    admin: User,
) -> None:
    """Crear un equipo con código ya registrado devuelve 409 CONFLICT."""
    await _crear_equipo(sesiones, "BE12-DUP-CODE")
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-DUP-CODE"},
        headers=cab,
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"


async def test_crear_equipo_sala_inexistente_devuelve_404(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """Crear un equipo con lab_id de una sala que no existe devuelve 404."""
    id_falso = "00000000-0000-4000-8000-000000000097"
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-NO-LAB", "lab_id": id_falso},
        headers=cab,
    )

    assert resp.status_code == 404


async def test_crear_equipo_no_incluye_secretos(
    cliente: AsyncClient,
    claves: str,
    admin: User,
) -> None:
    """La respuesta de crear equipo no expone credential_hash ni public_key_jwk."""
    cab = _cab_admin(claves, admin)

    resp = await cliente.post(
        f"{API}/admin/machines",
        json={"code": "BE12-SEC-NEW"},
        headers=cab,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert "credential_hash" not in body
    assert "public_key_jwk" not in body
    assert "key_thumbprint" not in body
