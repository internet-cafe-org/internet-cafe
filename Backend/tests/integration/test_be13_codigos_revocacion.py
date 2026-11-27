"""BE-13: códigos de enrolamiento y revocación de la clave del equipo.

Complementa ``test_admin_endpoints.py`` con el ciclo completo (generar, enrolar, revocar y
volver a enrolar), los equipos deshabilitados y la concurrencia entre enrolar y revocar.
"""

import asyncio
import base64
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.crypto import sha256_digest
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.main import app
from app.models import AuditLog, EnrollmentCode, Machine, MachineStatus, User, UserRole, UserStatus
from app.security import firma

API = "/api/v1"
BASE = "http://testserver"
ID_INEXISTENTE = "00000000-0000-4000-8000-000000000001"
Sesiones = async_sessionmaker[AsyncSession]


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


class EquipoP256:
    """Par P-256 de un equipo de prueba: arma el enrolamiento y firma peticiones."""

    def __init__(self) -> None:
        """Genera un par de claves nuevo."""
        self.clave = ec.generate_private_key(ec.SECP256R1())
        n = self.clave.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(n.x.to_bytes(32, "big")),
            "y": _b64url(n.y.to_bytes(32, "big")),
        }

    def firmar(self, mensaje: str) -> bytes:
        """Firma ``r||s`` de 64 bytes."""
        r, s = decode_dss_signature(self.clave.sign(mensaje.encode(), ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def cuerpo(self, codigo: str) -> dict[str, Any]:
        """Cuerpo de ``POST /machine/enroll``."""
        return {"enrollment_code": codigo, "jwk": self.jwk, "proof": _b64url(self.firmar(codigo))}

    def cabeceras(self, keyid: str, ruta: str) -> dict[str, str]:
        """Cabeceras RFC 9421 de un POST sin cuerpo."""
        params = (
            f'("@method" "@target-uri");created={int(time.time())};keyid="{keyid}";'
            f'alg="{firma.ALGORITMO}";nonce="{secrets.token_urlsafe(12)}"'
        )
        base = f'"@method": POST\n"@target-uri": {BASE}{ruta}\n"@signature-params": {params}'
        valor = base64.b64encode(self.firmar(base)).decode()
        return {"Signature-Input": f"sig1={params}", "Signature": f"sig1=:{valor}:"}


@pytest.fixture(autouse=True)
def _nonces_limpios() -> None:
    """Cada prueba empieza sin nonces vistos."""
    firma.nonces.reiniciar()


@pytest.fixture
async def cliente(
    sesiones: Sesiones, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP con claves ES256 efímeras y la base de pruebas inyectada."""
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    publica = (
        clave.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    monkeypatch.setattr(settings, "public_api_base_url", BASE)

    async def _db() -> AsyncIterator[AsyncSession]:
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    transporte = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transporte, base_url=BASE) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def cab_admin(cliente: AsyncClient, sesiones: Sesiones) -> dict[str, str]:
    """Cabeceras de un administrador activo (depende de ``cliente`` por las claves)."""
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
    token = create_access_token(
        subject=str(usuario.id), role=usuario.role.value, private_key=settings.jwt_private_key
    )
    return {"Authorization": f"Bearer {token}"}


async def _generar(cliente: AsyncClient, cab: dict[str, str], machine_id: Any) -> Response:
    return await cliente.post(f"{API}/admin/machines/{machine_id}/enrollment-code", headers=cab)


async def _revocar(cliente: AsyncClient, cab: dict[str, str], machine_id: Any) -> Response:
    return await cliente.post(f"{API}/admin/machines/{machine_id}/revoke-key", headers=cab)


async def _enrolar(cliente: AsyncClient, equipo: EquipoP256, codigo: str) -> Response:
    return await cliente.post(f"{API}/machine/enroll", json=equipo.cuerpo(codigo))


async def _pedir_reto(cliente: AsyncClient, equipo: EquipoP256, keyid: str) -> Response:
    ruta = f"{API}/machine/challenges"
    return await cliente.post(ruta, headers=equipo.cabeceras(keyid, ruta))


async def _estado(sesiones: Sesiones, machine_id: uuid.UUID, estado: MachineStatus) -> None:
    async with sesiones() as db:
        await db.execute(update(Machine).where(Machine.id == machine_id).values(status=estado))
        await db.commit()


async def _vivos(sesiones: Sesiones, machine_id: uuid.UUID) -> int:
    async with sesiones() as db:
        return await db.scalar(
            select(func.count())
            .select_from(EnrollmentCode)
            .where(EnrollmentCode.machine_id == machine_id, EnrollmentCode.used_at.is_(None))
        )


# ---------------------------------------------------------------- ciclo completo


async def test_generar_enrolar_revocar_y_volver_a_enrolar(cliente, cab_admin, datos) -> None:
    """El código sirve una vez; tras revocar, ni la firma ni un token autentican."""
    equipo = EquipoP256()
    codigo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    alta = await _enrolar(cliente, equipo, codigo)
    repetido = await _enrolar(cliente, EquipoP256(), codigo)
    keyid = alta.json()["keyid"]
    antes = await _pedir_reto(cliente, equipo, keyid)

    revocado = await _revocar(cliente, cab_admin, datos.pc01.id)
    con_firma = await _pedir_reto(cliente, equipo, keyid)
    con_token = await cliente.post(
        f"{API}/machine/challenges",
        headers={
            "X-Machine-Code": datos.pc01.code,
            "X-Machine-Key": "token-ficticio",
        },
    )
    nuevo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    otra_alta = await _enrolar(cliente, equipo, nuevo)

    assert (alta.status_code, repetido.status_code) == (201, 401)
    assert repetido.json()["code"] == "ENROLLMENT_CODE_INVALID"
    assert antes.status_code == 201
    assert (revocado.status_code, revocado.json()["status"]) == (200, "pending_enrollment")
    for resp in (con_firma, con_token):
        assert resp.status_code == 401
        assert resp.json()["code"] == "MACHINE_SIGNATURE_INVALID"
    assert otra_alta.status_code == 201


async def test_generar_otro_codigo_invalida_el_anterior(
    cliente, cab_admin, datos, sesiones
) -> None:
    """Solo queda vivo el último código, y los de otros equipos no se tocan."""
    ajeno = (await _generar(cliente, cab_admin, datos.pc02.id)).json()["code"]
    primero = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    segundo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]

    assert await _vivos(sesiones, datos.pc01.id) == 1
    assert (await _enrolar(cliente, EquipoP256(), primero)).status_code == 401
    assert (await _enrolar(cliente, EquipoP256(), segundo)).status_code == 201
    assert (await _enrolar(cliente, EquipoP256(), ajeno)).status_code == 201


async def test_revocar_es_idempotente_y_guarda_null_de_sql(
    cliente, cab_admin, datos, sesiones
) -> None:
    """Revocar dos veces responde 200 y la columna JSONB queda en NULL, no en JSON `null`."""
    await _generar(cliente, cab_admin, datos.pc01.id)

    respuestas = [await _revocar(cliente, cab_admin, datos.pc01.id) for _ in range(2)]

    assert [r.status_code for r in respuestas] == [200, 200]
    assert await _vivos(sesiones, datos.pc01.id) == 0
    async with sesiones() as db:
        es_null = await db.scalar(
            text("SELECT public_key_jwk IS NULL FROM app.machines WHERE id = :id"),
            {"id": datos.pc01.id},
        )
    assert es_null is True


@pytest.mark.parametrize("accion", [_generar, _revocar], ids=["generar", "revocar"])
async def test_equipo_inexistente_responde_404(cliente, cab_admin, accion) -> None:
    """Los dos endpoints responden 404 `NOT_FOUND` si el equipo no existe."""
    resp = await accion(cliente, cab_admin, ID_INEXISTENTE)

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- equipos deshabilitados


async def test_generar_para_un_equipo_deshabilitado_responde_409(
    cliente, cab_admin, datos, sesiones
) -> None:
    """Un equipo deshabilitado no recibe códigos."""
    await _estado(sesiones, datos.pc01.id, MachineStatus.disabled)

    resp = await _generar(cliente, cab_admin, datos.pc01.id)

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"
    assert await _vivos(sesiones, datos.pc01.id) == 0


async def test_revocar_conserva_deshabilitado_y_se_puede_rehabilitar(
    cliente, cab_admin, datos, sesiones
) -> None:
    """Revocar no rehabilita (RN-08); al activarlo después queda listo para enrolarse."""
    await _estado(sesiones, datos.pc01.id, MachineStatus.disabled)

    revocado = await _revocar(cliente, cab_admin, datos.pc01.id)
    bloqueado = await _generar(cliente, cab_admin, datos.pc01.id)
    activado = await cliente.patch(
        f"{API}/admin/machines/{datos.pc01.id}", headers=cab_admin, json={"status": "active"}
    )
    codigo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    alta = await _enrolar(cliente, EquipoP256(), codigo)

    assert (revocado.status_code, revocado.json()["status"]) == (200, "disabled")
    assert bloqueado.status_code == 409
    assert (activado.status_code, activado.json()["status"]) == (200, "pending_enrollment")
    assert alta.status_code == 201
    async with sesiones() as db:
        auditoria = await db.scalar(
            select(AuditLog).where(AuditLog.action == "machine_key_revoked")
        )
    assert auditoria.metadata_info["status"] == "disabled"


@pytest.mark.parametrize("estado", list(MachineStatus))
async def test_reto_solo_con_codigo_se_rechaza_siempre(cliente, datos, sesiones, estado) -> None:
    """Sin firma no hay QR, sea cual sea el estado del equipo (SEC-14)."""
    await _estado(sesiones, datos.pc01.id, estado)

    resp = await cliente.post(
        f"{API}/machine/challenges", headers={"X-Machine-Code": datos.pc01.code}
    )

    assert (resp.status_code, resp.json()["code"]) == (401, "MACHINE_SIGNATURE_INVALID")


@pytest.mark.parametrize(
    ("estado", "http", "code"),
    [
        (MachineStatus.disabled, 403, "MACHINE_DISABLED"),
        (MachineStatus.pending_enrollment, 401, "MACHINE_SIGNATURE_INVALID"),
    ],
)
async def test_reto_firmado_exige_equipo_activo(
    cliente, cab_admin, datos, sesiones, estado, http, code
) -> None:
    """Ni con una firma válida hay QR para un equipo deshabilitado o pendiente."""
    equipo = EquipoP256()
    codigo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    keyid = (await _enrolar(cliente, equipo, codigo)).json()["keyid"]
    await _estado(sesiones, datos.pc01.id, estado)

    resp = await _pedir_reto(cliente, equipo, keyid)

    assert (resp.status_code, resp.json()["code"]) == (http, code)


# ---------------------------------------------------------------- concurrencia


async def _esperar_bloqueo(sesiones: Sesiones) -> None:
    """Espera hasta que otra conexión de esta base esté detenida en un bloqueo."""
    async with sesiones() as db:
        for _ in range(100):
            n = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            await db.rollback()
            if n:
                return
            await asyncio.sleep(0.05)
    pytest.fail("Ninguna petición llegó a esperar el bloqueo del equipo.")


async def test_enrolar_espera_al_equipo_sin_retener_el_codigo(
    cliente, cab_admin, datos, sesiones
) -> None:
    """Regresión del interbloqueo: enrolar espera el equipo y luego ve el código invalidado."""
    codigo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
    async with sesiones() as db:
        await db.get(Machine, datos.pc01.id, with_for_update=True)
        tarea = asyncio.create_task(_enrolar(cliente, EquipoP256(), codigo))
        await _esperar_bloqueo(sesiones)
        # Lo mismo que hace revoke-key: con el orden anterior, aquí había deadlock.
        await db.execute(
            update(EnrollmentCode)
            .where(EnrollmentCode.code_hash == sha256_digest(codigo))
            .values(used_at=datetime.now(UTC))
        )
        await db.commit()
    resp = await asyncio.wait_for(tarea, 10)

    assert resp.status_code == 401
    assert resp.json()["code"] == "ENROLLMENT_CODE_INVALID"


async def test_enrolar_y_revocar_a_la_vez_no_dan_500(cliente, cab_admin, datos, sesiones) -> None:
    """Varias rondas en paralelo: sin 500 y, al final, a lo sumo un código vivo."""
    for _ in range(8):
        codigo = (await _generar(cliente, cab_admin, datos.pc01.id)).json()["code"]
        alta, baja, otro = await asyncio.gather(
            _enrolar(cliente, EquipoP256(), codigo),
            _revocar(cliente, cab_admin, datos.pc01.id),
            _generar(cliente, cab_admin, datos.pc01.id),
        )
        assert alta.status_code in (201, 401)
        assert baja.status_code == 200
        assert otro.status_code == 201
        assert await _vivos(sesiones, datos.pc01.id) <= 1
