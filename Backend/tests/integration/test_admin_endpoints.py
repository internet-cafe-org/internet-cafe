"""QA-07b: pruebas del administrador, el cierre forzado y el acceso por rol (HU-15).

Cubren sobre la API real (/api/v1) y PostgreSQL:
- control de acceso por rol: sin token, token vencido, firmado con otra clave, de estudiante y
  credenciales de equipo no abren ninguna ruta /admin (denegación por defecto);
- salas: crear, duplicados, validación, orden alfabético y paginación;
- equipos: listado con filtros, edición, deshabilitar (RN-08) y que no salgan secretos;
- accesos: filtros, paginación y código de estudiante enmascarado (RF-ADM-05);
- cierre forzado `admin_forced`: idempotente y con auditoría (RF-ADM-07, RF-SES-08, RF-ADM-09);
- recursos ajenos (IDOR) por rol: una sesión ajena responde igual que una inexistente.

Quedan marcadas como pendientes (skip) las pruebas de lo que aún no está en `develop`:
códigos de enrolamiento y revocación de clave (BE-13), CLI `block-user` (BE-20) y el filtro
por estudiante exacto de BE-14. Hay que activarlas cuando esas tareas se fusionen.

No hay credenciales reales: los tokens se firman con claves efímeras, los equipos usan una
credencial ficticia y los usuarios son datos inventados.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import (
    AccessSession,
    AuditActorType,
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
from app.security.dependencies import hash_machine_credential

API = "/api/v1"
CREDENCIAL_PC = "credencial-ficticia-de-pruebas"
ID_INEXISTENTE = "00000000-0000-4000-8000-000000000001"

# (nombre, método, ruta, cuerpo): todas las rutas de /admin con un cuerpo válido, para que un
# 401/403 solo pueda venir de la autorización y no de la validación.
RUTAS_ADMIN: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("listar salas", "GET", "/admin/labs", None),
    ("crear sala", "POST", "/admin/labs", {"name": "Sala intrusa"}),
    ("listar equipos", "GET", "/admin/machines", None),
    ("editar equipo", "PATCH", f"/admin/machines/{ID_INEXISTENTE}", {"mode": "kiosk"}),
    ("listar accesos", "GET", "/admin/sessions", None),
    ("cerrar acceso", "POST", f"/admin/sessions/{ID_INEXISTENTE}/end", None),
]

CAMPOS_DE_EQUIPO = {
    "id",
    "code",
    "hostname",
    "lab_id",
    "lab",
    "status",
    "mode",
    "app_version",
    "enrolled_at",
    "last_seen_at",
}


# ------------------------------------------------------------------------- Fixtures


def _par_de_claves() -> tuple[str, str]:
    """Par ES256 efímero (privada, pública) en PEM."""
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
    """Claves ES256 efímeras para la API; devuelve la privada con la que firma."""
    privada, publica = _par_de_claves()
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    return privada


@pytest.fixture
async def cliente(
    sesiones: async_sessionmaker[AsyncSession], claves: str
) -> AsyncIterator[AsyncClient]:
    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(sesiones: async_sessionmaker[AsyncSession]) -> User:
    """Un administrador activo con datos ficticios."""
    usuario = User(
        email_ct=b"admin@test.invalid",
        email_bidx=uuid.uuid4().bytes,
        full_name_ct=b"Administrador Prueba",
        password_hash="no-es-un-hash",
        role=UserRole.admin,
        status=UserStatus.active,
        privacy_consent_at=datetime.now(UTC),
    )
    async with sesiones() as db:
        db.add(usuario)
        await db.commit()
    return usuario


def _bearer(claves: str, usuario: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(usuario.id), role=usuario.role.value, private_key=claves
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cab_admin(claves: str, admin: User) -> dict[str, str]:
    """Cabeceras con el access token del administrador."""
    return _bearer(claves, admin)


@dataclass
class Accesos:
    sala_b: Lab
    cerrada: uuid.UUID  # de Ana en PC01 (Sala de pruebas), hace 2 h, cerrada
    abierta: uuid.UUID  # de Beto en PC02 (Sala B), hace 5 min, abierta


@pytest.fixture
async def accesos(sesiones: async_sessionmaker[AsyncSession], datos: Any) -> Accesos:
    """Dos accesos en dos salas distintas: uno cerrado y uno abierto."""
    async with sesiones() as db:
        sala_b = Lab(name="Sala B")
        db.add(sala_b)
        await db.flush()
        await db.execute(
            update(Machine).where(Machine.id == datos.pc02.id).values(lab_id=sala_b.id)
        )
        await db.commit()
    cerrada = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=120)
    abierta = await _crear_sesion(sesiones, datos.beto, datos.pc02, hace_min=5, abierta=True)
    return Accesos(sala_b=sala_b, cerrada=cerrada, abierta=abierta)


# ---------------------------------------------------------------------------- Ayudas


async def _crear_sesion(
    sesiones: async_sessionmaker[AsyncSession],
    usuario: User,
    equipo: Machine,
    *,
    hace_min: int,
    abierta: bool = False,
    motivo: SessionEndReason = SessionEndReason.user_logout_pc,
) -> uuid.UUID:
    """Inserta un reto aprobado y la sesión que origina, empezada hace `hace_min` minutos."""
    inicio = datetime.now(UTC) - timedelta(minutes=hace_min)
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
            ended_at=None if abierta else inicio + timedelta(minutes=1),
            end_reason=None if abierta else motivo,
        )
        db.add(sesion)
        await db.commit()
        return sesion.id


async def _leer_sesion(
    sesiones: async_sessionmaker[AsyncSession], sesion_id: uuid.UUID
) -> AccessSession:
    async with sesiones() as db:
        return (
            await db.execute(select(AccessSession).where(AccessSession.id == sesion_id))
        ).scalar_one()


async def _leer_equipo(
    sesiones: async_sessionmaker[AsyncSession], equipo_id: uuid.UUID
) -> Machine:
    async with sesiones() as db:
        return (await db.execute(select(Machine).where(Machine.id == equipo_id))).scalar_one()


async def _contar(sesiones: async_sessionmaker[AsyncSession], modelo: Any) -> int:
    async with sesiones() as db:
        return (await db.execute(select(func.count()).select_from(modelo))).scalar_one()


async def _auditorias(
    sesiones: async_sessionmaker[AsyncSession], accion: str
) -> list[AuditLog]:
    async with sesiones() as db:
        filas = await db.execute(
            select(AuditLog).where(AuditLog.action == accion).order_by(AuditLog.id)
        )
        return list(filas.scalars().all())


async def _dar_credencial(
    sesiones: async_sessionmaker[AsyncSession], equipo: Machine
) -> dict[str, str]:
    """Le pone al equipo una credencial ficticia y devuelve las cabeceras para usarla."""
    credencial = f"{CREDENCIAL_PC}-{equipo.code}"
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == equipo.id)
            .values(credential_hash=hash_machine_credential(credencial))
        )
        await db.commit()
    return {"X-Machine-Code": equipo.code, "X-Machine-Key": credencial}


async def _fallos_en_rutas_admin(
    cliente: AsyncClient, cabeceras: dict[str, str] | None, status: int, code: str
) -> list[str]:
    """Rutas de /admin que NO respondieron `status` con ese `code` usando esas cabeceras."""
    fallos: list[str] = []
    for nombre, metodo, ruta, cuerpo in RUTAS_ADMIN:
        resp = await cliente.request(metodo, f"{API}{ruta}", headers=cabeceras, json=cuerpo)
        if resp.status_code != status or resp.json().get("code") != code:
            fallos.append(f"{nombre}: {resp.status_code} {resp.text[:120]}")
    return fallos


def _sin_instance(resp: Response) -> dict[str, Any]:
    """Cuerpo del error sin `instance`, que cambia con la URL pedida."""
    cuerpo: dict[str, Any] = resp.json()
    cuerpo.pop("instance", None)
    return cuerpo


# ------------------------------------------------------------ Control de acceso por rol


async def test_sin_token_ninguna_ruta_admin_responde(cliente: AsyncClient) -> None:
    fallos = await _fallos_en_rutas_admin(cliente, None, 401, "AUTH_INVALID_CREDENTIALS")

    assert fallos == []


async def test_token_de_estudiante_recibe_403_en_toda_ruta_admin(
    cliente: AsyncClient, claves: str, datos: Any
) -> None:
    fallos = await _fallos_en_rutas_admin(
        cliente, _bearer(claves, datos.ana), 403, "FORBIDDEN"
    )

    assert fallos == []


async def test_token_de_admin_vencido_no_entra(
    cliente: AsyncClient, claves: str, admin: User
) -> None:
    token = create_access_token(
        subject=str(admin.id),
        role="admin",
        private_key=claves,
        expires_delta=timedelta(minutes=-5),
    )

    fallos = await _fallos_en_rutas_admin(
        cliente, {"Authorization": f"Bearer {token}"}, 401, "AUTH_TOKEN_EXPIRED"
    )

    assert fallos == []


async def test_token_con_rol_admin_firmado_con_otra_clave_no_entra(
    cliente: AsyncClient, admin: User
) -> None:
    clave_ajena, _ = _par_de_claves()
    token = create_access_token(subject=str(admin.id), role="admin", private_key=clave_ajena)

    fallos = await _fallos_en_rutas_admin(
        cliente, {"Authorization": f"Bearer {token}"}, 401, "AUTH_INVALID_CREDENTIALS"
    )

    assert fallos == []


async def test_credenciales_de_equipo_no_abren_las_rutas_admin(
    cliente: AsyncClient, sesiones: async_sessionmaker[AsyncSession], datos: Any
) -> None:
    cabeceras = await _dar_credencial(sesiones, datos.pc01)

    fallos = await _fallos_en_rutas_admin(cliente, cabeceras, 401, "AUTH_INVALID_CREDENTIALS")

    assert fallos == []


async def test_intentos_de_estudiante_no_cambian_nada(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    sesion_id = await _crear_sesion(sesiones, datos.beto, datos.pc01, hace_min=5, abierta=True)
    cabeceras = _bearer(claves, datos.ana)
    salas_antes = await _contar(sesiones, Lab)

    await cliente.post(f"{API}/admin/labs", headers=cabeceras, json={"name": "Sala intrusa"})
    await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cabeceras, json={"status": "disabled"}
    )
    await cliente.post(f"{API}/admin/sessions/{sesion_id}/end", headers=cabeceras)

    assert await _contar(sesiones, Lab) == salas_antes
    assert (await _leer_equipo(sesiones, datos.pc01.id)).status == MachineStatus.active
    assert (await _leer_sesion(sesiones, sesion_id)).ended_at is None
    assert await _auditorias(sesiones, "lab_created") == []
    assert await _auditorias(sesiones, "machine_updated") == []
    assert await _auditorias(sesiones, "session_ended") == []


# ------------------------------------------------------------------------------ Salas


async def test_admin_crea_una_sala_y_queda_auditada(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    admin: User,
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    resp = await cliente.post(
        f"{API}/admin/labs", headers=cab_admin, json={"name": "Sala Norte", "building": "Bloque B"}
    )

    assert resp.status_code == 201
    sala = resp.json()
    assert (sala["name"], sala["building"]) == ("Sala Norte", "Bloque B")
    listado = (await cliente.get(f"{API}/admin/labs", headers=cab_admin)).json()
    assert [s["name"] for s in listado["items"]] == ["Sala Norte"]
    auditorias = await _auditorias(sesiones, "lab_created")
    assert len(auditorias) == 1
    assert auditorias[0].actor_type == AuditActorType.user
    assert auditorias[0].actor_id == admin.id
    assert str(auditorias[0].target_id) == sala["id"]


async def test_nombre_de_sala_se_guarda_sin_espacios_sobrantes(
    cliente: AsyncClient, cab_admin: dict[str, str]
) -> None:
    resp = await cliente.post(f"{API}/admin/labs", headers=cab_admin, json={"name": "  Sala Sur  "})

    assert resp.status_code == 201
    assert resp.json()["name"] == "Sala Sur"


async def test_sala_con_nombre_repetido_responde_conflicto(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    await cliente.post(f"{API}/admin/labs", headers=cab_admin, json={"name": "Sala Norte"})

    resp = await cliente.post(f"{API}/admin/labs", headers=cab_admin, json={"name": "Sala Norte"})

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"
    assert await _contar(sesiones, Lab) == 1
    assert len(await _auditorias(sesiones, "lab_created")) == 1


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 81},
        {"name": "Sala X", "building": "y" * 81},
        {"name": "Sala X", "rol": "admin"},
    ],
    ids=["sin nombre", "vacío", "solo espacios", "81 letras", "edificio largo", "campo extra"],
)
async def test_crear_sala_rechaza_datos_invalidos(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    cuerpo: dict[str, Any],
) -> None:
    resp = await cliente.post(f"{API}/admin/labs", headers=cab_admin, json=cuerpo)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert await _contar(sesiones, Lab) == 0


async def test_salas_salen_en_orden_alfabetico_y_paginadas(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
) -> None:
    async with sesiones() as db:
        db.add_all([Lab(name=f"Sala {n:02d}") for n in range(25, 0, -1)])
        await db.commit()

    primera = (await cliente.get(f"{API}/admin/labs", headers=cab_admin)).json()
    segunda = (await cliente.get(f"{API}/admin/labs?offset=20", headers=cab_admin)).json()

    assert (primera["total"], primera["limit"], len(primera["items"])) == (25, 20, 20)
    assert len(segunda["items"]) == 5
    nombres = [s["name"] for s in primera["items"] + segunda["items"]]
    assert nombres == [f"Sala {n:02d}" for n in range(1, 26)]


@pytest.mark.parametrize("consulta", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
async def test_salas_rechazan_paginacion_fuera_de_rango(
    cliente: AsyncClient, cab_admin: dict[str, str], consulta: str
) -> None:
    resp = await cliente.get(f"{API}/admin/labs?{consulta}", headers=cab_admin)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------- Equipos


async def test_equipos_se_listan_con_su_estado_y_sin_secretos(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    cabeceras_pc = await _dar_credencial(sesiones, datos.pc01)
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == datos.pc01.id)
            .values(
                key_thumbprint="huella-ficticia-de-pruebas",
                public_key_jwk={"kty": "EC", "crv": "P-256", "x": "x-ficticia", "y": "y-ficticia"},
            )
        )
        await db.commit()

    resp = await cliente.get(f"{API}/admin/machines", headers=cab_admin)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["total"] == 2
    assert [e["code"] for e in cuerpo["items"]] == ["LAB-TEST-PC01", "LAB-TEST-PC02"]
    pc01 = cuerpo["items"][0]
    assert (pc01["lab"], pc01["status"], pc01["mode"]) == ("Sala de pruebas", "active", "passive")
    for equipo in cuerpo["items"]:
        assert set(equipo) == CAMPOS_DE_EQUIPO
    for secreto in (
        cabeceras_pc["X-Machine-Key"],
        hash_machine_credential(cabeceras_pc["X-Machine-Key"]),
        "huella-ficticia-de-pruebas",
        "x-ficticia",
    ):
        assert secreto not in resp.text


async def test_equipos_se_filtran_por_sala_y_por_estado(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    accesos: Accesos,
) -> None:
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == datos.pc02.id)
            .values(status=MachineStatus.disabled)
        )
        await db.commit()

    por_sala = (
        await cliente.get(f"{API}/admin/machines?lab_id={accesos.sala_b.id}", headers=cab_admin)
    ).json()
    por_estado = (
        await cliente.get(f"{API}/admin/machines?status=disabled", headers=cab_admin)
    ).json()
    sin_resultados = (
        await cliente.get(f"{API}/admin/machines?status=pending_enrollment", headers=cab_admin)
    ).json()

    assert [e["code"] for e in por_sala["items"]] == ["LAB-TEST-PC02"]
    assert [e["code"] for e in por_estado["items"]] == ["LAB-TEST-PC02"]
    assert (sin_resultados["total"], sin_resultados["items"]) == (0, [])


@pytest.mark.parametrize(
    "consulta", ["limit=0", "limit=101", "offset=-1", "status=otro", "lab_id=no-es-uuid"]
)
async def test_equipos_rechazan_filtros_invalidos(
    cliente: AsyncClient, cab_admin: dict[str, str], consulta: str
) -> None:
    resp = await cliente.get(f"{API}/admin/machines?{consulta}", headers=cab_admin)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_admin_cambia_el_modo_de_un_equipo_y_queda_auditado(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    admin: User,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    resp = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cab_admin, json={"mode": "kiosk"}
    )

    assert resp.status_code == 200
    assert resp.json()["mode"] == "kiosk"
    assert (await _leer_equipo(sesiones, datos.pc01.id)).mode.value == "kiosk"
    auditorias = await _auditorias(sesiones, "machine_updated")
    assert len(auditorias) == 1
    assert auditorias[0].actor_id == admin.id
    assert auditorias[0].target_id == datos.pc01.id
    assert auditorias[0].metadata_info == {"fields": ["mode"]}


async def test_admin_mueve_un_equipo_de_sala_y_se_la_quita(
    cliente: AsyncClient, cab_admin: dict[str, str], datos: Any, accesos: Accesos
) -> None:
    ruta = f"{API}/admin/machines/{datos.pc01.id}"

    movido = await cliente.patch(ruta, headers=cab_admin, json={"lab_id": str(accesos.sala_b.id)})
    sin_sala = await cliente.patch(ruta, headers=cab_admin, json={"lab_id": None})

    assert movido.status_code == 200
    assert movido.json()["lab"] == "Sala B"
    assert sin_sala.status_code == 200
    assert (sin_sala.json()["lab_id"], sin_sala.json()["lab"]) == (None, None)


async def test_editar_equipo_con_sala_inexistente_responde_404_y_no_cambia_nada(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    resp = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}",
        headers=cab_admin,
        json={"lab_id": ID_INEXISTENTE, "mode": "kiosk"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"
    equipo = await _leer_equipo(sesiones, datos.pc01.id)
    assert (equipo.lab_id, equipo.mode.value) == (datos.lab.id, "passive")


async def test_editar_un_equipo_inexistente_responde_404(
    cliente: AsyncClient, cab_admin: dict[str, str]
) -> None:
    resp = await cliente.patch(
        f"{API}/admin/machines/{ID_INEXISTENTE}", headers=cab_admin, json={"mode": "kiosk"}
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"status": "pending_enrollment"},
        {"status": "otro"},
        {"mode": "otro"},
        {"lab_id": "no-es-uuid"},
        {"hostname": "otro-nombre"},
    ],
    ids=["vacío", "no se puede volver a pendiente", "estado raro", "modo raro", "sala no uuid", "campo extra"],
)
async def test_editar_equipo_rechaza_datos_invalidos(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    cuerpo: dict[str, Any],
) -> None:
    resp = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cab_admin, json=cuerpo
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert (await _leer_equipo(sesiones, datos.pc01.id)).status == MachineStatus.active


async def test_editar_equipo_con_id_que_no_es_uuid_responde_422(
    cliente: AsyncClient, cab_admin: dict[str, str]
) -> None:
    resp = await cliente.patch(
        f"{API}/admin/machines/no-es-uuid", headers=cab_admin, json={"mode": "kiosk"}
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_no_se_puede_activar_un_equipo_que_no_se_enrolo(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == datos.pc01.id)
            .values(status=MachineStatus.pending_enrollment, enrolled_at=None)
        )
        await db.commit()

    resp = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cab_admin, json={"status": "active"}
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"
    assert (await _leer_equipo(sesiones, datos.pc01.id)).status == MachineStatus.pending_enrollment


async def test_un_equipo_enrolado_se_puede_deshabilitar_y_volver_a_activar(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    async with sesiones() as db:
        await db.execute(
            update(Machine)
            .where(Machine.id == datos.pc01.id)
            .values(enrolled_at=datetime.now(UTC))
        )
        await db.commit()
    ruta = f"{API}/admin/machines/{datos.pc01.id}"

    apagado = await cliente.patch(ruta, headers=cab_admin, json={"status": "disabled"})
    repetido = await cliente.patch(ruta, headers=cab_admin, json={"status": "disabled"})
    encendido = await cliente.patch(ruta, headers=cab_admin, json={"status": "active"})

    assert [r.status_code for r in (apagado, repetido, encendido)] == [200, 200, 200]
    assert (apagado.json()["status"], encendido.json()["status"]) == ("disabled", "active")


async def test_deshabilitar_un_equipo_cancela_sus_retos_y_cierra_su_sesion(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    admin: User,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    sesion_id = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    async with sesiones() as db:
        reto = LoginChallenge(
            machine_id=datos.pc01.id,
            token_hash=uuid.uuid4().bytes,
            status=ChallengeStatus.pending,
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        db.add(reto)
        await db.commit()
    cabeceras_pc = await _dar_credencial(sesiones, datos.pc01)

    resp = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cab_admin, json={"status": "disabled"}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
    sesion = await _leer_sesion(sesiones, sesion_id)
    assert sesion.ended_at is not None
    assert sesion.end_reason == SessionEndReason.admin_forced
    async with sesiones() as db:
        estado = (
            await db.execute(select(LoginChallenge.status).where(LoginChallenge.id == reto.id))
        ).scalar_one()
    assert estado == ChallengeStatus.cancelled
    cierres = await _auditorias(sesiones, "session_ended")
    assert [(c.actor_id, c.target_id) for c in cierres] == [(admin.id, sesion_id)]
    assert cierres[0].metadata_info == {"end_reason": "admin_forced"}
    # RN-08: el equipo deshabilitado ya no puede enviar latidos
    latido = await cliente.post(f"{API}/machine/heartbeat", headers=cabeceras_pc, json=None)
    assert latido.status_code == 403
    assert latido.json()["code"] == "MACHINE_DISABLED"


# ---------------------------------------------------------------------------- Accesos


async def test_accesos_salen_del_mas_reciente_con_el_codigo_enmascarado(
    cliente: AsyncClient, cab_admin: dict[str, str], datos: Any, accesos: Accesos
) -> None:
    resp = await cliente.get(f"{API}/admin/sessions", headers=cab_admin)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert (cuerpo["total"], cuerpo["limit"], cuerpo["offset"]) == (2, 20, 0)
    abierto, cerrado = cuerpo["items"]
    assert abierto["id"] == str(accesos.abierta)
    assert abierto["user"] == {
        "id": str(datos.beto.id),
        "full_name": "Estudiante Prueba 2",
        "student_code_masked": "0000****02",
    }
    assert (abierto["machine_code"], abierto["lab"]) == ("LAB-TEST-PC02", "Sala B")
    assert (abierto["ended_at"], abierto["end_reason"], abierto["duration_s"]) == (None, None, None)
    assert cerrado["id"] == str(accesos.cerrada)
    assert (cerrado["end_reason"], cerrado["duration_s"]) == ("user_logout_pc", 60)
    assert cerrado["user"]["student_code_masked"] == "0000****01"
    for dato_sensible in ("0000000001", "0000000002", "password_hash", "@test.invalid"):
        assert dato_sensible not in resp.text


async def test_accesos_se_filtran_por_equipo_sala_y_estado(
    cliente: AsyncClient, cab_admin: dict[str, str], accesos: Accesos, datos: Any
) -> None:
    async def ids(consulta: str) -> list[str]:
        resp = await cliente.get(f"{API}/admin/sessions?{consulta}", headers=cab_admin)
        assert resp.status_code == 200
        return [i["id"] for i in resp.json()["items"]]

    assert await ids("machine_code=LAB-TEST-PC02") == [str(accesos.abierta)]
    assert await ids(f"lab_id={accesos.sala_b.id}") == [str(accesos.abierta)]
    assert await ids(f"lab_id={datos.lab.id}") == [str(accesos.cerrada)]
    assert await ids("state=active") == [str(accesos.abierta)]
    assert await ids("state=ended") == [str(accesos.cerrada)]
    assert await ids("machine_code=NO-EXISTE") == []
    assert await ids("state=active&machine_code=LAB-TEST-PC01") == []


async def test_accesos_se_filtran_por_fechas(
    cliente: AsyncClient, cab_admin: dict[str, str], accesos: Accesos
) -> None:
    corte = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()

    async def ids(**parametros: str) -> list[str]:
        resp = await cliente.get(f"{API}/admin/sessions", params=parametros, headers=cab_admin)
        assert resp.status_code == 200
        return [i["id"] for i in resp.json()["items"]]

    assert await ids(started_from=corte) == [str(accesos.abierta)]
    assert await ids(started_to=corte) == [str(accesos.cerrada)]
    # Una fecha sin zona horaria se interpreta como UTC
    assert len(await ids(started_from="2000-01-01T00:00:00")) == 2


@pytest.mark.parametrize(
    "consulta",
    [
        "state=otro",
        "limit=0",
        "limit=101",
        "offset=-1",
        "lab_id=no-es-uuid",
        "started_from=ayer",
        f"machine_code={'X' * 41}",
    ],
)
async def test_accesos_rechazan_filtros_invalidos(
    cliente: AsyncClient, cab_admin: dict[str, str], consulta: str
) -> None:
    resp = await cliente.get(f"{API}/admin/sessions?{consulta}", headers=cab_admin)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_accesos_paginan_de_20_en_20(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    for minutos in range(25, 0, -1):
        await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=minutos * 10)

    primera = (await cliente.get(f"{API}/admin/sessions", headers=cab_admin)).json()
    segunda = (await cliente.get(f"{API}/admin/sessions?offset=20", headers=cab_admin)).json()

    assert (primera["total"], len(primera["items"]), len(segunda["items"])) == (25, 20, 5)
    inicios = [i["started_at"] for i in primera["items"] + segunda["items"]]
    assert inicios == sorted(inicios, reverse=True)


# ------------------------------------------------------------------- Cierre forzado


async def test_admin_cierra_un_acceso_abierto_y_queda_auditado(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    admin: User,
    sesiones: async_sessionmaker[AsyncSession],
    accesos: Accesos,
) -> None:
    resp = await cliente.post(f"{API}/admin/sessions/{accesos.abierta}/end", headers=cab_admin)

    assert resp.status_code == 200
    cerrado = resp.json()["session"]
    assert cerrado["id"] == str(accesos.abierta)
    assert cerrado["end_reason"] == "admin_forced"
    assert cerrado["ended_at"] is not None
    assert cerrado["duration_s"] >= 0
    sesion = await _leer_sesion(sesiones, accesos.abierta)
    assert sesion.end_reason == SessionEndReason.admin_forced
    cierres = await _auditorias(sesiones, "session_ended")
    assert len(cierres) == 1
    assert cierres[0].actor_type == AuditActorType.user
    assert cierres[0].actor_id == admin.id
    assert cierres[0].target_id == accesos.abierta
    assert cierres[0].metadata_info == {"end_reason": "admin_forced"}


async def test_cerrar_dos_veces_el_mismo_acceso_no_cambia_nada_ni_audita_de_nuevo(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    accesos: Accesos,
) -> None:
    ruta = f"{API}/admin/sessions/{accesos.abierta}/end"

    primera = await cliente.post(ruta, headers=cab_admin)
    segunda = await cliente.post(ruta, headers=cab_admin)

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json()["session"]["ended_at"] == primera.json()["session"]["ended_at"]
    assert len(await _auditorias(sesiones, "session_ended")) == 1


async def test_cierre_forzado_no_pisa_el_motivo_de_un_acceso_ya_cerrado(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    accesos: Accesos,
) -> None:
    antes = await _leer_sesion(sesiones, accesos.cerrada)

    resp = await cliente.post(f"{API}/admin/sessions/{accesos.cerrada}/end", headers=cab_admin)

    assert resp.status_code == 200
    assert resp.json()["session"]["end_reason"] == "user_logout_pc"
    despues = await _leer_sesion(sesiones, accesos.cerrada)
    assert (despues.ended_at, despues.end_reason) == (antes.ended_at, antes.end_reason)
    assert await _auditorias(sesiones, "session_ended") == []


async def test_cerrar_un_acceso_inexistente_responde_404(
    cliente: AsyncClient, cab_admin: dict[str, str], sesiones: async_sessionmaker[AsyncSession]
) -> None:
    resp = await cliente.post(f"{API}/admin/sessions/{ID_INEXISTENTE}/end", headers=cab_admin)

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"
    assert await _auditorias(sesiones, "session_ended") == []


async def test_cerrar_un_acceso_con_id_que_no_es_uuid_responde_422(
    cliente: AsyncClient, cab_admin: dict[str, str]
) -> None:
    resp = await cliente.post(f"{API}/admin/sessions/no-es-uuid/end", headers=cab_admin)

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_el_equipo_se_entera_del_cierre_forzado_en_su_proximo_latido(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
) -> None:
    sesion_id = await _crear_sesion(sesiones, datos.ana, datos.pc01, hace_min=5, abierta=True)
    cabeceras_pc = await _dar_credencial(sesiones, datos.pc01)
    await cliente.post(f"{API}/admin/sessions/{sesion_id}/end", headers=cab_admin)

    latido = await cliente.post(
        f"{API}/machine/heartbeat", headers=cabeceras_pc, json={"session_id": str(sesion_id)}
    )

    assert latido.status_code == 200
    cuerpo = latido.json()
    assert cuerpo["session_status"] == "ended"
    assert cuerpo["session_id"] == str(sesion_id)
    assert cuerpo["end_reason"] == "admin_forced"


# ------------------------------------------------------- Recursos ajenos (IDOR) por rol


async def test_admin_no_cierra_el_acceso_de_un_estudiante_por_la_ruta_del_estudiante(
    cliente: AsyncClient,
    cab_admin: dict[str, str],
    sesiones: async_sessionmaker[AsyncSession],
    accesos: Accesos,
) -> None:
    resp = await cliente.post(f"{API}/me/sessions/{accesos.abierta}/end", headers=cab_admin)

    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"
    assert (await _leer_sesion(sesiones, accesos.abierta)).ended_at is None


async def test_estudiante_no_cierra_la_sesion_de_otro_y_la_respuesta_es_igual_a_una_inexistente(
    cliente: AsyncClient,
    claves: str,
    sesiones: async_sessionmaker[AsyncSession],
    datos: Any,
    accesos: Accesos,
) -> None:
    cabeceras = _bearer(claves, datos.ana)  # la sesión abierta es de Beto

    ajena = await cliente.post(f"{API}/me/sessions/{accesos.abierta}/end", headers=cabeceras)
    inexistente = await cliente.post(f"{API}/me/sessions/{ID_INEXISTENTE}/end", headers=cabeceras)

    assert ajena.status_code == inexistente.status_code == 404
    assert _sin_instance(ajena) == _sin_instance(inexistente)
    assert (await _leer_sesion(sesiones, accesos.abierta)).ended_at is None


async def test_ruta_admin_no_delata_a_un_estudiante_si_un_id_existe(
    cliente: AsyncClient, claves: str, datos: Any, accesos: Accesos
) -> None:
    cabeceras = _bearer(claves, datos.ana)

    real = await cliente.post(f"{API}/admin/sessions/{accesos.abierta}/end", headers=cabeceras)
    falso = await cliente.post(f"{API}/admin/sessions/{ID_INEXISTENTE}/end", headers=cabeceras)

    assert real.status_code == falso.status_code == 403
    assert _sin_instance(real) == _sin_instance(falso)


async def test_estudiante_no_ve_los_accesos_ajenos_por_la_ruta_admin(
    cliente: AsyncClient, claves: str, datos: Any, accesos: Accesos
) -> None:
    resp = await cliente.get(f"{API}/admin/sessions", headers=_bearer(claves, datos.ana))

    assert resp.status_code == 403
    assert "Estudiante Prueba" not in resp.text
    assert "LAB-TEST" not in resp.text


# --------------------------------------------------- Pendientes de otras tareas (skip)
# Se activan cuando la tarea de la que dependen se fusione en `develop`. Hoy no existen ni
# las rutas ni el CLI, así que no hay nada que probar todavía.


@pytest.mark.skip(reason="BE-13 aún no está en develop: códigos de enrolamiento")
async def test_codigo_de_enrolamiento_se_muestra_una_sola_vez() -> None:
    """Al generar el código se ve completo una vez; una consulta posterior no lo devuelve.

    Debe comprobar también que solo el admin puede generarlo (401 sin token, 403 de
    estudiante), que el código no queda en claro en la base ni en los logs y que la
    generación queda auditada.
    """


@pytest.mark.skip(reason="BE-13 aún no está en develop: revocación de la clave del equipo")
async def test_revocar_la_clave_de_un_equipo_lo_deja_sin_poder_autenticarse() -> None:
    """Tras revocar, el equipo ya no firma ni usa su credencial, y la revocación se audita."""


@pytest.mark.skip(reason="BE-20 aún no está en develop: CLI create-admin y block-user")
async def test_block_user_bloquea_la_cuenta_revoca_sesiones_web_y_cierra_el_acceso() -> None:
    """RN-12: bloquear una cuenta la deja en `blocked`, revoca sus refresh tokens y cierra su
    acceso activo con `admin_forced`; un usuario inexistente falla sin cambiar nada.
    """


@pytest.mark.skip(reason="BE-14: el filtro por estudiante exacto aún no está en develop")
async def test_accesos_se_filtran_por_estudiante_con_correo_o_codigo_exacto() -> None:
    """HU-15: el filtro usa el correo o el código exacto a través del blind index; una parte
    del código o del correo no devuelve resultados.
    """