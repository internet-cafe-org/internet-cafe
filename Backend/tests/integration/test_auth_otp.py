"""ST-SEC-01: pruebas de integración de OTP (verify-email, resend-code, forgot y reset)."""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from freezegun import freeze_time
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.database import obtener_base_datos
from app.main import app
from app.models import (
    AuditLog,
    EmailCode,
    EmailCodePurpose,
    EmailOutbox,
    RefreshToken,
    User,
    UserStatus,
)
from app.services import pii, refresh_tokens
from app.services.passwords import verify_password

RUTA = "/api/v1/auth"
CORREO = "otp.estudiante@test.invalid"
CLAVE_INICIAL = "ClaveInicial-2026"
CLAVE_NUEVA = "ClaveNueva-2026-ok"
CLAVE_INDICE = bytes(range(32)).hex()
CLAVE_OTP = "c" * 64


def _extraer_codigo_de_outbox(fila: EmailOutbox) -> str:
    """Descifra el payload del outbox y extrae el código OTP de 6 dígitos."""
    assert fila.payload_ct is not None
    bruto = pii.revelar(fila.payload_ct, aad=f"email_outbox.payload_ct.{fila.id}")
    datos = json.loads(bruto)
    coincidencia = re.search(r"\b(\d{6})\b", datos["texto"])
    assert coincidencia is not None
    return coincidencia.group(1)


@pytest.fixture
def claves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura llaves ES256, índice ciego, cifrado PII y llave HMAC del OTP."""
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
    monkeypatch.setattr(settings, "jwt_private_key", privada)
    monkeypatch.setattr(settings, "jwt_public_key", publica)
    monkeypatch.setattr(settings, "blind_index_key", CLAVE_INDICE)
    monkeypatch.setattr(settings, "otp_hmac_key", CLAVE_OTP)
    monkeypatch.setattr(settings, "allowed_email_domains", "")
    monkeypatch.setattr(settings, "require_email_verification", True)


@pytest.fixture
async def cliente(sesiones, claves):
    """Cliente HTTP contra FastAPI conectado a la base de pruebas."""

    async def _db():
        async with sesiones() as db:
            yield db

    app.dependency_overrides[obtener_base_datos] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _registrar_pendiente(
    cliente: AsyncClient, correo: str = CORREO, codigo_est: str = "2026000101"
) -> None:
    resp = await cliente.post(
        f"{RUTA}/register",
        json={
            "email": correo,
            "student_code": codigo_est,
            "full_name": "Estudiante OTP",
            "password": CLAVE_INICIAL,
            "privacy_consent": True,
        },
    )
    assert resp.status_code == 202


async def _ultimo_outbox(sesiones, plantilla: str | None = None) -> EmailOutbox:
    async with sesiones() as db:
        consulta = select(EmailOutbox)
        if plantilla is not None:
            consulta = consulta.where(EmailOutbox.template == plantilla)
        fila = await db.scalar(
            consulta.order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc()).limit(1)
        )
        assert fila is not None
        return fila


# ---------------------------------------------------------------- verify-email


async def test_verify_email_flujo_exitoso_activa_cuenta_y_permite_login(cliente, sesiones):
    await _registrar_pendiente(cliente)
    outbox = await _ultimo_outbox(sesiones, "verify_email")
    assert pii.revelar(outbox.to_ct, aad=f"email_outbox.to_ct.{outbox.id}") == CORREO
    codigo = _extraer_codigo_de_outbox(outbox)

    resp = await cliente.post(
        f"{RUTA}/verify-email", json={"email": "  OTP.Estudiante@TEST.invalid ", "code": codigo}
    )

    assert resp.status_code == 204
    assert resp.content == b""

    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        registro = await db.scalar(
            select(EmailCode).where(EmailCode.purpose == EmailCodePurpose.verify_email)
        )
        acciones = list((await db.scalars(select(AuditLog.action))).all())
    assert usuario is not None
    assert usuario.status == UserStatus.active
    assert usuario.email_verified_at is not None
    assert registro is not None and registro.consumed_at is not None
    assert "auth.verify_email" in acciones

    login = await cliente.post(f"{RUTA}/login", json={"email": CORREO, "password": CLAVE_INICIAL})
    assert login.status_code == 200


async def test_verify_email_codigo_ya_usado_devuelve_409(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    primera = await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo})
    assert primera.status_code == 204

    segunda = await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo})

    assert segunda.status_code == 409
    assert segunda.json()["code"] == "OTP_ALREADY_USED"


async def test_verify_email_codigo_invalido_y_correo_inexistente(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo_real = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    codigo_malo = "000000" if codigo_real != "000000" else "999999"

    resp_malo = await cliente.post(
        f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_malo}
    )
    resp_inexistente = await cliente.post(
        f"{RUTA}/verify-email", json={"email": "nadie@test.invalid", "code": "123456"}
    )

    assert resp_malo.status_code == 400
    assert resp_malo.json()["code"] == "OTP_INVALID"
    assert resp_inexistente.status_code == 400
    assert resp_inexistente.json()["code"] == "OTP_INVALID"

    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        registro = await db.scalar(select(EmailCode))
    assert usuario is not None and usuario.status == UserStatus.pending_verification
    assert registro is not None and registro.attempts == 1


async def test_verify_email_bloqueo_tras_5_intentos_fallidos(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo_real = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    codigo_malo = "000000" if codigo_real != "000000" else "999999"

    for _ in range(5):
        fallo = await cliente.post(
            f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_malo}
        )
        assert fallo.status_code == 400
        assert fallo.json()["code"] == "OTP_INVALID"

    sexto = await cliente.post(
        f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_real}
    )

    assert sexto.status_code == 429
    assert sexto.json()["code"] == "OTP_MAX_ATTEMPTS"
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        registro = await db.scalar(select(EmailCode))
    assert usuario is not None and usuario.status == UserStatus.pending_verification
    assert registro is not None and registro.attempts == 5 and registro.consumed_at is None


async def test_verify_email_codigo_expirado_devuelve_410(cliente, sesiones):
    with freeze_time("2026-11-26 10:00:00") as reloj:
        await _registrar_pendiente(cliente)
        codigo = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))

        reloj.tick(timedelta(minutes=10, seconds=1))
        resp = await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo})

    assert resp.status_code == 410
    assert resp.json()["code"] == "OTP_EXPIRED"
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
    assert usuario is not None and usuario.status == UserStatus.pending_verification


# ---------------------------------------------------------------- resend-code


async def test_resend_code_invalida_codigo_anterior_y_encola_nuevo(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo_1 = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))

    reenvio = await cliente.post(f"{RUTA}/resend-code", json={"email": CORREO})

    assert reenvio.status_code == 202
    assert reenvio.content == b""
    codigo_2 = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))

    # El primer código ya no sirve, incluso si por azar coincidiera o no.
    if codigo_1 != codigo_2:
        resp_viejo = await cliente.post(
            f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_1}
        )
        assert resp_viejo.status_code == 400
        assert resp_viejo.json()["code"] == "OTP_INVALID"

    resp_nuevo = await cliente.post(
        f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_2}
    )
    assert resp_nuevo.status_code == 204


async def test_resend_code_no_revela_cuenta_inexistente_o_ya_activa(cliente, sesiones):
    resp_inexistente = await cliente.post(
        f"{RUTA}/resend-code", json={"email": "no.existe@test.invalid"}
    )
    assert resp_inexistente.status_code == 202

    await _registrar_pendiente(cliente)
    codigo = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    assert (await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo})).status_code == 204

    resp_activa = await cliente.post(f"{RUTA}/resend-code", json={"email": CORREO})
    assert resp_activa.status_code == 202
    async with sesiones() as db:
        total_outbox = await db.scalar(select(func.count()).select_from(EmailOutbox))
    assert total_outbox == 1


async def test_resend_code_limita_3_envios_por_hora_y_libera_luego(cliente, sesiones):
    with freeze_time("2026-11-26 10:00:00") as reloj:
        await _registrar_pendiente(cliente)

        respuestas = [
            await cliente.post(f"{RUTA}/resend-code", json={"email": CORREO})
            for _ in range(4)
        ]

        assert [r.status_code for r in respuestas[:3]] == [202, 202, 202]
        assert respuestas[3].status_code == 429
        assert respuestas[3].json()["code"] == "RATE_LIMITED"
        assert int(respuestas[3].headers["retry-after"]) >= 1

        async with sesiones() as db:
            total_outbox = await db.scalar(select(func.count()).select_from(EmailOutbox))
        # 1 del registro + 3 de resend-code (el 4.º bloqueado no encola correo).
        assert total_outbox == 4

        reloj.tick(timedelta(hours=1, minutes=1))
        despues = await cliente.post(f"{RUTA}/resend-code", json={"email": CORREO})
        assert despues.status_code == 202


# ---------------------------------------------------------------- forgot y reset


async def test_forgot_respuesta_generica_y_no_encola_para_inexistentes_o_pendientes(
    cliente, sesiones
):
    await _registrar_pendiente(cliente)

    r_inexistente = await cliente.post(
        f"{RUTA}/password/forgot", json={"email": "desconocido@test.invalid"}
    )
    r_pendiente = await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})

    assert r_inexistente.status_code == 202 and r_inexistente.content == b""
    assert r_pendiente.status_code == 202 and r_pendiente.content == b""
    async with sesiones() as db:
        reset_codes = await db.scalar(
            select(func.count())
            .select_from(EmailCode)
            .where(EmailCode.purpose == EmailCodePurpose.reset_password)
        )
    assert reset_codes == 0


async def test_forgot_y_reset_flujo_exitoso_revoca_sesiones_y_encola_aviso(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo_verif = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    assert (
        await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_verif})
    ).status_code == 204

    # Crea una sesión web previa para comprobar que reset la revoca.
    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        assert usuario is not None
        rt_previo = await refresh_tokens.emitir(db, usuario.id, "pytest")
        await db.commit()

    forgot = await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})
    assert forgot.status_code == 202
    assert forgot.content == b""

    outbox_reset = await _ultimo_outbox(sesiones, "reset_password")
    codigo_reset = _extraer_codigo_de_outbox(outbox_reset)

    reset = await cliente.post(
        f"{RUTA}/password/reset",
        json={"email": CORREO, "code": codigo_reset, "new_password": CLAVE_NUEVA},
    )
    assert reset.status_code == 204
    assert reset.content == b""

    async with sesiones() as db:
        usuario = await db.scalar(select(User))
        codigo_db = await db.scalar(
            select(EmailCode).where(EmailCode.purpose == EmailCodePurpose.reset_password)
        )
        rt_db = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == refresh_tokens.hash_token(rt_previo)
            )
        )
        aviso = await db.scalar(
            select(EmailOutbox).where(EmailOutbox.template == "password_changed")
        )
        acciones = list((await db.scalars(select(AuditLog.action))).all())

    assert usuario is not None and verify_password(CLAVE_NUEVA, usuario.password_hash)
    assert codigo_db is not None and codigo_db.consumed_at is not None
    assert rt_db is not None and rt_db.revoked_at is not None
    assert aviso is not None
    assert "auth.password_forgot" in acciones
    assert "auth.password_reset" in acciones

    login_viejo = await cliente.post(
        f"{RUTA}/login", json={"email": CORREO, "password": CLAVE_INICIAL}
    )
    login_nuevo = await cliente.post(
        f"{RUTA}/login", json={"email": CORREO, "password": CLAVE_NUEVA}
    )
    assert login_viejo.status_code == 401
    assert login_nuevo.status_code == 200


async def test_reset_codigo_invalido_usado_expirado_y_5_intentos(cliente, sesiones):
    with freeze_time("2026-11-26 12:00:00") as reloj:
        await _registrar_pendiente(cliente)
        codigo_verif = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
        await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_verif})

        # 1) Política de contraseña inválida -> 422 sin exponer la clave.
        assert (await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})).status_code == 202
        codigo_1 = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "reset_password"))
        corta = await cliente.post(
            f"{RUTA}/password/reset",
            json={"email": CORREO, "code": codigo_1, "new_password": "corta"},
        )
        assert corta.status_code == 422
        assert corta.json()["code"] == "VALIDATION_ERROR"
        assert "corta" not in corta.text

        # 2) Bloqueo tras 5 intentos fallidos -> 6.º intento da 429 OTP_MAX_ATTEMPTS.
        codigo_malo = "000000" if codigo_1 != "000000" else "999999"
        for _ in range(5):
            r = await cliente.post(
                f"{RUTA}/password/reset",
                json={"email": CORREO, "code": codigo_malo, "new_password": CLAVE_NUEVA},
            )
            assert r.status_code == 400
            assert r.json()["code"] == "OTP_INVALID"
        bloqueado = await cliente.post(
            f"{RUTA}/password/reset",
            json={"email": CORREO, "code": codigo_1, "new_password": CLAVE_NUEVA},
        )
        assert bloqueado.status_code == 429
        assert bloqueado.json()["code"] == "OTP_MAX_ATTEMPTS"

        # 3) Código expirado (>10 min) -> 410 OTP_EXPIRED.
        assert (await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})).status_code == 202
        codigo_2 = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "reset_password"))
        reloj.tick(timedelta(minutes=10, seconds=1))
        expirado = await cliente.post(
            f"{RUTA}/password/reset",
            json={"email": CORREO, "code": codigo_2, "new_password": CLAVE_NUEVA},
        )
        assert expirado.status_code == 410
        assert expirado.json()["code"] == "OTP_EXPIRED"

        # 4) Uso exitoso y luego reutilización -> 409 OTP_ALREADY_USED.
        assert (await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})).status_code == 202
        codigo_3 = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "reset_password"))
        assert (
            await cliente.post(
                f"{RUTA}/password/reset",
                json={"email": CORREO, "code": codigo_3, "new_password": CLAVE_NUEVA},
            )
        ).status_code == 204
        reusado = await cliente.post(
            f"{RUTA}/password/reset",
            json={"email": CORREO, "code": codigo_3, "new_password": "OtraClave-2026-ok"},
        )
        assert reusado.status_code == 409
        assert reusado.json()["code"] == "OTP_ALREADY_USED"


async def test_forgot_respeta_limite_3_por_hora(cliente, sesiones):
    await _registrar_pendiente(cliente)
    codigo_verif = _extraer_codigo_de_outbox(await _ultimo_outbox(sesiones, "verify_email"))
    await cliente.post(f"{RUTA}/verify-email", json={"email": CORREO, "code": codigo_verif})

    respuestas = [
        await cliente.post(f"{RUTA}/password/forgot", json={"email": CORREO})
        for _ in range(4)
    ]

    assert [r.status_code for r in respuestas[:3]] == [202, 202, 202]
    assert respuestas[3].status_code == 429
    assert respuestas[3].json()["code"] == "RATE_LIMITED"
    assert int(respuestas[3].headers["retry-after"]) >= 1
    assert datetime.now(UTC) is not None
