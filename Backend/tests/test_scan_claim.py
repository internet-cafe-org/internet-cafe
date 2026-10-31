import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AccessSession,
    ChallengeStatus,
    Lab,
    LoginChallenge,
    Machine,
    MachineStatus,
    SessionEndReason,
)
from app.services import challenges, events


# =====================================================================
# 1. PRUEBAS DE DOMINIO Y LÓGICA TRANSACCIONAL (challenges.py)
# =====================================================================

@pytest.mark.asyncio
async def test_servicio_claim_camino_feliz():
    """Prueba unitaria del servicio: camino feliz con aprobación y notificación."""
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = "token-secreto-valido-123"
    token_bytes = challenges.hash_token(token)
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    # Mock del reto
    reto = LoginChallenge(
        id=uuid.uuid4(),
        machine_id=machine_id,
        token_hash=token_bytes,
        status=ChallengeStatus.pending,
        expires_at=now + timedelta(seconds=60),
    )

    # Mock de la máquina
    lab_id = uuid.uuid4()
    machine = Machine(
        id=machine_id,
        code="LAB1-PC01",
        lab_id=lab_id,
        status=MachineStatus.active,
    )
    lab = Lab(id=lab_id, name="Laboratorio de Redes")

    # Mock de la sesión de BD
    mock_db = AsyncMock()

    # Configurar retornos de queries execute
    def mock_execute_side_effect(stmt):
        mock_result = MagicMock()
        stmt_str = str(stmt)
        if "app.login_challenges.token_hash" in stmt_str:
            mock_result.scalar_one_or_none.return_value = reto
        elif "app.machines.id" in stmt_str:
            mock_result.scalar_one.return_value = machine
        elif "app.access_sessions.machine_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            # Sin sesiones activas en la máquina (no busy)
            mock_result.first.return_value = None
        elif "app.access_sessions.user_id" in stmt_str and "ended_at IS NULL" in stmt_str:
            # Sin sesiones activas previas del usuario (no superseded)
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
        elif "app.login_challenges.machine_id" in stmt_str and "status = :status_1" in stmt_str:
            # Retos residuales a cancelar
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
        elif "app.labs.id" in stmt_str:
            mock_result.scalar_one_or_none.return_value = lab
        else:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.first.return_value = None
        return mock_result

    mock_db.execute.side_effect = mock_execute_side_effect

    listener = events.subscribe(machine_id)

    with patch("app.services.challenges.audit", new_callable=AsyncMock) as mock_audit:
        sesion, ret_machine, lab_name, is_idempotent = await challenges.reclamar_reto_qr(
            db=mock_db,
            token=token,
            user_id=user_id,
            now=now,
        )

        assert not is_idempotent
        assert reto.status == ChallengeStatus.approved
        assert reto.approved_by == user_id
        assert reto.approved_at == now
        assert ret_machine.code == "LAB1-PC01"
        assert lab_name == "Laboratorio de Redes"
        assert sesion.user_id == user_id
        assert sesion.machine_id == machine_id

        # Verificación de auditoría y commit
        mock_audit.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

        # Verificación de notify al long-poll
        assert listener.is_set()
        events.unsubscribe(machine_id, listener)


@pytest.mark.asyncio
async def test_servicio_claim_idempotencia():
    """El mismo usuario envía el mismo token y recibe la misma sesión (idempotente)."""
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    challenge_id = uuid.uuid4()
    token = "token-idempotente-xyz"
    token_bytes = challenges.hash_token(token)

    reto = LoginChallenge(
        id=challenge_id,
        machine_id=machine_id,
        token_hash=token_bytes,
        status=ChallengeStatus.approved,
        approved_by=user_id,
    )
    sesion_existente = AccessSession(
        id=uuid.uuid4(),
        user_id=user_id,
        machine_id=machine_id,
        challenge_id=challenge_id,
        started_at=datetime.now(timezone.utc),
    )
    machine = Machine(id=machine_id, code="PC-IDEMP", status=MachineStatus.active, lab_id=None)

    mock_db = AsyncMock()
    def mock_execute(stmt):
        res = MagicMock()
        s = str(stmt)
        if "app.login_challenges.token_hash" in s:
            res.scalar_one_or_none.return_value = reto
        elif "app.access_sessions.challenge_id" in s:
            res.scalar_one_or_none.return_value = sesion_existente
        elif "app.machines.id" in s:
            res.scalar_one.return_value = machine
        return res

    mock_db.execute.side_effect = mock_execute

    sesion, ret_machine, lab_name, is_idempotent = await challenges.reclamar_reto_qr(
        db=mock_db,
        token=token,
        user_id=user_id,
    )

    assert is_idempotent is True
    assert sesion.id == sesion_existente.id
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_servicio_claim_ya_usado_por_otro():
    """Si el reto ya fue aprobado por otro estudiante, lanza ChallengeAlreadyUsedError."""
    machine_id = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    token = "token-ya-usado"

    reto = LoginChallenge(
        id=uuid.uuid4(),
        machine_id=machine_id,
        token_hash=challenges.hash_token(token),
        status=ChallengeStatus.approved,
        approved_by=user_a,
    )

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = reto
    mock_db.execute.return_value = mock_res

    with pytest.raises(challenges.ChallengeAlreadyUsedError):
        await challenges.reclamar_reto_qr(mock_db, token, user_b)


@pytest.mark.asyncio
async def test_servicio_claim_expirado():
    """Si el reto venció por TTL de 60s, lanza ChallengeExpiredError y lo marca expired."""
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = "token-vencido"
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    reto = LoginChallenge(
        id=uuid.uuid4(),
        machine_id=machine_id,
        token_hash=challenges.hash_token(token),
        status=ChallengeStatus.pending,
        expires_at=now - timedelta(seconds=1),
    )

    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = reto
    mock_db.execute.return_value = mock_res

    with pytest.raises(challenges.ChallengeExpiredError):
        await challenges.reclamar_reto_qr(mock_db, token, user_id, now=now)

    assert reto.status == ChallengeStatus.expired
    mock_db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_servicio_claim_machine_busy():
    """Si el equipo ya tiene una sesión abierta por otro usuario, lanza MachineBusyError."""
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = "token-busy"
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    reto = LoginChallenge(
        id=uuid.uuid4(),
        machine_id=machine_id,
        token_hash=challenges.hash_token(token),
        status=ChallengeStatus.pending,
        expires_at=now + timedelta(seconds=60),
    )
    machine = Machine(id=machine_id, code="BUSY-PC", status=MachineStatus.active)
    sesion_activa = AccessSession(id=uuid.uuid4(), machine_id=machine_id, ended_at=None)

    mock_db = AsyncMock()
    def mock_execute(stmt):
        res = MagicMock()
        s = str(stmt)
        if "app.login_challenges.token_hash" in s:
            res.scalar_one_or_none.return_value = reto
        elif "app.machines.id" in s:
            res.scalar_one.return_value = machine
        elif "app.access_sessions.machine_id" in s:
            res.first.return_value = (sesion_activa,)
        return res

    mock_db.execute.side_effect = mock_execute

    with pytest.raises(challenges.MachineBusyError):
        await challenges.reclamar_reto_qr(mock_db, token, user_id, now=now)


@pytest.mark.asyncio
async def test_servicio_claim_superseded():
    """Cierra la sesión activa previa del estudiante en otro equipo con motivo superseded."""
    m1_id = uuid.uuid4()
    m2_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = "token-m2"
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    reto_m2 = LoginChallenge(
        id=uuid.uuid4(),
        machine_id=m2_id,
        token_hash=challenges.hash_token(token),
        status=ChallengeStatus.pending,
        expires_at=now + timedelta(seconds=60),
    )
    m2 = Machine(id=m2_id, code="PC-2", status=MachineStatus.active, lab_id=None)
    sesion_previa_m1 = AccessSession(
        id=uuid.uuid4(),
        user_id=user_id,
        machine_id=m1_id,
        challenge_id=uuid.uuid4(),
        started_at=now - timedelta(minutes=10),
        ended_at=None,
        end_reason=None,
    )

    mock_db = AsyncMock()
    def mock_execute(stmt):
        res = MagicMock()
        res.first.return_value = None
        s = str(stmt)
        if "app.login_challenges.token_hash" in s:
            res.scalar_one_or_none.return_value = reto_m2
        elif "app.machines.id" in s:
            res.scalar_one.return_value = m2
        elif "app.access_sessions.user_id" in s:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = [sesion_previa_m1]
            res.scalars.return_value = mock_scalars
        elif "app.access_sessions.machine_id" in s:
            res.first.return_value = None
        elif "app.login_challenges.machine_id" in s:
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            res.scalars.return_value = mock_scalars
        return res

    mock_db.execute.side_effect = mock_execute

    with patch("app.services.challenges.audit", new_callable=AsyncMock):
        await challenges.reclamar_reto_qr(mock_db, token, user_id, now=now)

    assert sesion_previa_m1.ended_at == now
    assert sesion_previa_m1.end_reason == SessionEndReason.superseded


# =====================================================================
# 2. PRUEBAS DE INTEGRACIÓN HTTP DE LA API (scan.py / RFC 9457)
# =====================================================================

@pytest.mark.asyncio
async def test_api_claim_201_creado():
    """POST /scan/claim crea la sesión y retorna 201 Created."""
    sesion_mock = AccessSession(
        id=uuid.uuid4(),
        started_at=datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc),
        ended_at=None,
    )
    machine_mock = Machine(id=uuid.uuid4(), code="LAB1-PC05")

    with patch("app.services.challenges.reclamar_reto_qr", new_callable=AsyncMock) as mock_claim:
        mock_claim.return_value = (sesion_mock, machine_mock, "Sala de Prueba", False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/v1/scan/claim", json={"token": "tok123"})

        assert res.status_code == 201
        data = res.json()
        assert data["session"]["status"] == "active"
        assert data["session"]["machine"]["code"] == "LAB1-PC05"
        assert data["session"]["machine"]["lab"] == "Sala de Prueba"


@pytest.mark.asyncio
async def test_api_claim_200_idempotente():
    """POST /scan/claim reintentado por el mismo usuario retorna 200 OK."""
    sesion_mock = AccessSession(
        id=uuid.uuid4(),
        started_at=datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc),
        ended_at=None,
    )
    machine_mock = Machine(id=uuid.uuid4(), code="LAB1-PC05")

    with patch("app.services.challenges.reclamar_reto_qr", new_callable=AsyncMock) as mock_claim:
        mock_claim.return_value = (sesion_mock, machine_mock, "Sala de Prueba", True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/v1/scan/claim", json={"token": "tok123"})

        assert res.status_code == 200


@pytest.mark.asyncio
async def test_api_claim_errores_rfc9457():
    """POST /scan/claim valida el catálogo de errores RFC 9457."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:

        # 404 CHALLENGE_NOT_FOUND
        with patch("app.services.challenges.reclamar_reto_qr", side_effect=challenges.ChallengeNotFoundError):
            res = await ac.post("/api/v1/scan/claim", json={"token": "fake"})
            assert res.status_code == 404
            assert res.json()["code"] == "CHALLENGE_NOT_FOUND"

        # 410 CHALLENGE_EXPIRED
        with patch("app.services.challenges.reclamar_reto_qr", side_effect=challenges.ChallengeExpiredError):
            res = await ac.post("/api/v1/scan/claim", json={"token": "expired"})
            assert res.status_code == 410
            assert res.json()["code"] == "CHALLENGE_EXPIRED"

        # 409 CHALLENGE_ALREADY_USED
        with patch("app.services.challenges.reclamar_reto_qr", side_effect=challenges.ChallengeAlreadyUsedError):
            res = await ac.post("/api/v1/scan/claim", json={"token": "used"})
            assert res.status_code == 409
            assert res.json()["code"] == "CHALLENGE_ALREADY_USED"

        # 409 MACHINE_BUSY
        with patch("app.services.challenges.reclamar_reto_qr", side_effect=challenges.MachineBusyError):
            res = await ac.post("/api/v1/scan/claim", json={"token": "busy"})
            assert res.status_code == 409
            assert res.json()["code"] == "MACHINE_BUSY"

        # 403 MACHINE_DISABLED
        with patch("app.services.challenges.reclamar_reto_qr", side_effect=challenges.MachineNotActiveError):
            res = await ac.post("/api/v1/scan/claim", json={"token": "disabled"})
            assert res.status_code == 403
            assert res.json()["code"] == "MACHINE_DISABLED"
