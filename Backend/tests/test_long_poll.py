import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AccessSession,
    Machine,
    MachineStatus,
    User,
    UserRole,
    UserStatus,
)
from app.services import challenges, events


@pytest.fixture(autouse=True)
def clean_events():
    events.reset_events()
    yield
    events.reset_events()


def test_mask_student_code():
    """Valida el enmascaramiento seguro del código de estudiante (SRS §9.1 / RNF-PRI-02)."""
    assert challenges.mask_student_code("2021102034") == "2021****34"
    assert challenges.mask_student_code("20211020034") == "2021*****34"
    assert challenges.mask_student_code("123456") == "12**56"
    assert challenges.mask_student_code("1234") == "****"
    assert challenges.mask_student_code("") == "********"
    assert challenges.mask_student_code(None) == "********"


@pytest.mark.asyncio
async def test_long_poll_despierta_con_evento_approved():
    """Camino feliz: el long-poll espera hasta que notify() despierta con la sesión aprobada."""
    machine_id = uuid.uuid4()
    machine = Machine(
        id=machine_id,
        code="LAB1-PC01",
        status=MachineStatus.active,
    )

    mock_db = AsyncMock()

    # Primera llamada a execute: get_current_machine -> devuelve machine
    # Segunda llamada: obtener_sesion_activa_equipo -> no hay sesión previa
    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "app.machines.code" in stmt_str:
            mock_res.scalar_one_or_none.return_value = machine
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    session_id = uuid.uuid4()
    now_iso = datetime.now(timezone.utc).isoformat()
    session_payload = {
        "status": "approved",
        "session": {
            "id": str(session_id),
            "status": "active",
            "started_at": now_iso,
        },
        "user": {
            "full_name": "Carlos Gomez",
            "student_code_masked": "2021****34",
        },
        "recent_accesses": [],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Lanzamos la petición de long-poll como tarea asíncrona
        async def do_request():
            return await client.get(
                "/api/v1/machine/challenges/wait?timeout=2",
                headers={"x-machine-code": "LAB1-PC01"},
            )

        wait_task = asyncio.create_task(do_request())

        # Esperamos brevemente a que el long-poll se haya suscrito y liberado la BD
        await asyncio.sleep(0.05)

        # Verificamos que se suscribió en memoria
        assert machine_id in events._listeners
        assert len(events._listeners[machine_id]) == 1

        # Simulamos la confirmación del claim despertando al equipo
        events.notify(machine_id, session_payload)

        # Obtenemos la respuesta del long-poll
        response = await wait_task

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["session"]["id"] == str(session_id)
    assert data["session"]["status"] == "active"
    assert data["user"]["full_name"] == "Carlos Gomez"
    assert data["user"]["student_code_masked"] == "2021****34"
    assert data["recent_accesses"] == []

    # Verificamos que se soltó la conexión de BD
    mock_db.close.assert_awaited()

    # Verificamos desuscripción sin fugas de memoria
    assert machine_id not in events._listeners


@pytest.mark.asyncio
async def test_long_poll_sesion_activa_inmediata():
    """Si el equipo ya tiene una sesión activa en BD, responde approved de inmediato sin esperar."""
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    machine = Machine(
        id=machine_id,
        code="LAB1-PC02",
        status=MachineStatus.active,
    )
    sesion = AccessSession(
        id=uuid.uuid4(),
        machine_id=machine_id,
        user_id=user_id,
        started_at=datetime.now(timezone.utc),
        ended_at=None,
    )
    user = User(
        id=user_id,
        email_ct=b"ana@escuela.edu",
        email_bidx=b"idx1",
        full_name_ct=b"Ana Perez",
        student_code_ct=b"2021102034",
        password_hash="hash",
        privacy_consent_at=datetime.now(timezone.utc),
    )

    mock_db = AsyncMock()

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "app.machines.code" in stmt_str:
            mock_res.scalar_one_or_none.return_value = machine
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            mock_res.scalar_one_or_none.return_value = sesion
        elif "app.users.id" in stmt_str:
            mock_res.scalar_one_or_none.return_value = user
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start_time = asyncio.get_event_loop().time()
        response = await client.get(
            "/api/v1/machine/challenges/wait?timeout=25",
            headers={"x-machine-code": "LAB1-PC02"},
        )
        elapsed = asyncio.get_event_loop().time() - start_time

    app.dependency_overrides.clear()

    # Responde de inmediato (< 500 ms)
    assert elapsed < 0.5
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["session"]["id"] == str(sesion.id)
    assert data["user"]["full_name"] == "Ana Perez"
    assert data["user"]["student_code_masked"] == "2021****34"
    assert data["recent_accesses"] == []

    # Verificamos que soltó la conexión y no dejó listeners
    mock_db.close.assert_awaited()
    assert machine_id not in events._listeners


@pytest.mark.asyncio
async def test_long_poll_timeout_waiting():
    """Si no hay notificación dentro del timeout, responde status: waiting (SRS §8.1)."""
    machine_id = uuid.uuid4()
    machine = Machine(
        id=machine_id,
        code="LAB1-PC03",
        status=MachineStatus.active,
    )

    mock_db = AsyncMock()

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        if "app.machines.code" in stmt_str:
            mock_res.scalar_one_or_none.return_value = machine
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Timeout corto de 1 segundo para la prueba
        response = await client.get(
            "/api/v1/machine/challenges/wait?timeout=1",
            headers={"x-machine-code": "LAB1-PC03"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "waiting"}

    # Verificamos que soltó la conexión antes de esperar
    mock_db.close.assert_awaited()
    # Verificamos que desuscribió el evento
    assert machine_id not in events._listeners


@pytest.mark.asyncio
async def test_long_poll_errores_autenticacion_y_estado():
    """Valida los códigos de error RFC 9457 esperados."""
    machine_active_id = uuid.uuid4()
    machine_disabled_id = uuid.uuid4()

    machine_active = Machine(id=machine_active_id, code="PC-ACTIVE", status=MachineStatus.active)
    machine_disabled = Machine(id=machine_disabled_id, code="PC-DISABLED", status=MachineStatus.disabled)

    mock_db = AsyncMock()

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        params = getattr(stmt.compile(), "params", {})
        param_values = list(params.values())

        if "PC-ACTIVE" in param_values:
            mock_res.scalar_one_or_none.return_value = machine_active
        elif "PC-DISABLED" in param_values:
            mock_res.scalar_one_or_none.return_value = machine_disabled
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Sin header x-machine-code -> 422
        res_no_header = await client.get("/api/v1/machine/challenges/wait")
        assert res_no_header.status_code == 422

        # 2. Máquina no existe -> 401 MACHINE_SIGNATURE_INVALID
        res_401 = await client.get(
            "/api/v1/machine/challenges/wait",
            headers={"x-machine-code": "PC-NO-EXISTE"},
        )
        assert res_401.status_code == 401
        assert res_401.json()["code"] == "MACHINE_SIGNATURE_INVALID"

        # 3. Máquina deshabilitada -> 403 MACHINE_DISABLED (RN-08)
        res_403 = await client.get(
            "/api/v1/machine/challenges/wait",
            headers={"x-machine-code": "PC-DISABLED"},
        )
        assert res_403.status_code == 403
        assert res_403.json()["code"] == "MACHINE_DISABLED"

        # 4. Timeout fuera de rango (> 25) -> 422
        res_422_timeout_high = await client.get(
            "/api/v1/machine/challenges/wait?timeout=50",
            headers={"x-machine-code": "PC-ACTIVE"},
        )
        assert res_422_timeout_high.status_code == 422

        # 5. Timeout fuera de rango (< 1) -> 422
        res_422_timeout_low = await client.get(
            "/api/v1/machine/challenges/wait?timeout=0",
            headers={"x-machine-code": "PC-ACTIVE"},
        )
        assert res_422_timeout_low.status_code == 422

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_long_poll_aislamiento_entre_equipos():
    """Verifica que dos equipos en long-poll concurrente no interfieran entre sí (no hay diafonía)."""
    machine1_id = uuid.uuid4()
    machine2_id = uuid.uuid4()

    machine1 = Machine(id=machine1_id, code="PC-01", status=MachineStatus.active)
    machine2 = Machine(id=machine2_id, code="PC-02", status=MachineStatus.active)

    mock_db = AsyncMock()

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt)
        params = getattr(stmt.compile(), "params", {})
        param_values = list(params.values())

        if "PC-01" in param_values:
            mock_res.scalar_one_or_none.return_value = machine1
        elif "PC-02" in param_values:
            mock_res.scalar_one_or_none.return_value = machine2
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    payload1 = {
        "status": "approved",
        "session": {
            "id": str(uuid.uuid4()),
            "status": "active",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        "user": {
            "full_name": "Estudiante 1",
            "student_code_masked": "2021****01",
        },
        "recent_accesses": [],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Lanzamos espera para ambos equipos
        task1 = asyncio.create_task(
            client.get("/api/v1/machine/challenges/wait?timeout=2", headers={"x-machine-code": "PC-01"})
        )
        task2 = asyncio.create_task(
            client.get("/api/v1/machine/challenges/wait?timeout=1", headers={"x-machine-code": "PC-02"})
        )

        await asyncio.sleep(0.05)

        # Solo notificamos a PC-01
        events.notify(machine1_id, payload1)

        res1 = await task1
        res2 = await task2

    app.dependency_overrides.clear()

    # PC-01 fue despertado y aprobado
    assert res1.status_code == 200
    assert res1.json()["status"] == "approved"
    assert res1.json()["user"]["full_name"] == "Estudiante 1"

    # PC-02 venció por timeout sin verse afectado por el evento de PC-01
    assert res2.status_code == 200
    assert res2.json()["status"] == "waiting"

    # Ambos quedaron limpios en el despachador de eventos
    assert machine1_id not in events._listeners
    assert machine2_id not in events._listeners


@pytest.mark.asyncio
async def test_long_poll_fallback_db_al_despertar():
    """Si al despertar el payload no está en memoria, consulta la BD como respaldo seguro."""
    machine_id = uuid.uuid4()
    machine = Machine(id=machine_id, code="PC-FALLBACK", status=MachineStatus.active)
    sesion = AccessSession(
        id=uuid.uuid4(),
        machine_id=machine_id,
        user_id=uuid.uuid4(),
        started_at=datetime.now(timezone.utc),
        ended_at=None,
    )

    mock_db = AsyncMock()

    # Primera consulta de sesion_activa da None (no hay sesion antes de esperar)
    # Tras despertar, fallback en BD encuentra la sesion
    consultas_sesion = 0

    def mock_execute(stmt):
        nonlocal consultas_sesion
        mock_res = MagicMock()
        stmt_str = str(stmt)
        params = getattr(stmt.compile(), "params", {})
        param_values = list(params.values())

        if "PC-FALLBACK" in param_values:
            mock_res.scalar_one_or_none.return_value = machine
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            consultas_sesion += 1
            if consultas_sesion == 1:
                mock_res.scalar_one_or_none.return_value = None
            else:
                mock_res.scalar_one_or_none.return_value = sesion
        elif "app.users.id" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        else:
            mock_res.scalar_one_or_none.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_execute

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[obtener_base_datos] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.routers.machine.SesionLocalAsync") as mock_session_local:
            mock_fallback_session = AsyncMock()
            mock_fallback_session.execute.side_effect = mock_execute
            mock_session_local.return_value.__aenter__.return_value = mock_fallback_session

            task = asyncio.create_task(
                client.get("/api/v1/machine/challenges/wait?timeout=2", headers={"x-machine-code": "PC-FALLBACK"})
            )
            await asyncio.sleep(0.05)

            # Notificamos SIN data (payload = None)
            events.notify(machine_id, None)

            res = await task

    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "approved"
    assert data["session"]["id"] == str(sesion.id)
    assert machine_id not in events._listeners

