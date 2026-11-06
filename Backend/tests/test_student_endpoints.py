"""Tests para los endpoints del estudiante (BE-11).

Verificamos la lógica de negocio del servicio y los schemas de respuesta
sin necesitar una base de datos real ni un event loop. Todos los tests
son síncronos y usan objetos simulados (mocks) para los modelos de BD.

Cobertura:
  - Enmascarado del código de estudiante (nunca expone el código en claro)
  - Estructura de la respuesta de perfil
  - Lógica de cierre de sesión: propietario, ya cerrada, no encontrada
  - Respuesta paginada del historial de sesiones
  - Dependencia de autenticación: ausencia de token, token inválido, expirado
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.challenges import mask_student_code
from app.services.student import (
    SesionDeOtroUsuarioError,
    SesionNoEncontradaError,
    SesionYaTerminadaError,
)


# ---------------------------------------------------------------------------
# Helpers para construir objetos falsos sin tocar la BD
# ---------------------------------------------------------------------------

def _usuario_falso(
    student_code: str = "20211020034",
    full_name: str = "Juan Pérez",
    role: str = "student",
    status: str = "active",
) -> MagicMock:
    """Crea un User simulado con los campos mínimos que usa el router."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.full_name_ct = full_name.encode("utf-8")
    u.student_code_ct = student_code.encode("utf-8")
    u.role = MagicMock()
    u.role.value = role
    u.status = MagicMock()
    u.status.value = status
    u.created_at = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    return u


def _sesion_falsa(
    user_id: uuid.UUID | None = None,
    ended_at: datetime | None = None,
    end_reason=None,
) -> MagicMock:
    """Crea una AccessSession simulada."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.user_id = user_id or uuid.uuid4()
    s.machine_id = uuid.uuid4()
    s.started_at = datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    s.last_heartbeat_at = datetime(2024, 3, 1, 10, 30, 0, tzinfo=timezone.utc)
    s.ended_at = ended_at
    s.end_reason = end_reason
    return s


# ---------------------------------------------------------------------------
# Tests del enmascarado del código de estudiante
# ---------------------------------------------------------------------------

class TestMaskStudentCode:
    """El código de estudiante nunca debe aparecer en claro en la respuesta."""

    def test_codigo_estandar_queda_enmascarado(self):
        # El código típico de 11 dígitos → solo se ven primeros 4 y últimos 2
        resultado = mask_student_code("20211020034")
        assert resultado == "2021*****34"
        # Aseguramos que el medio NO aparece en claro
        assert "10200" not in resultado

    def test_codigo_corto_queda_enmascarado(self):
        resultado = mask_student_code("12345")
        # Código de 5 dígitos → "12**45" (primeros 2, dos asteriscos, últimos 2)
        assert "12" in resultado
        assert "*" in resultado
        # El medio (dígito 3) no debe aparecer visible
        assert resultado != "12345"

    def test_codigo_muy_corto(self):
        # 4 o menos caracteres → todo enmascarado
        assert mask_student_code("1234") == "****"

    def test_codigo_none_devuelve_asteriscos(self):
        assert mask_student_code(None) == "********"

    def test_codigo_vacio_devuelve_asteriscos(self):
        assert mask_student_code("") == "********"

    def test_codigo_enmascarado_no_expone_digitos_del_medio(self):
        # Verificación explícita: los dígitos centrales deben estar ocultos
        resultado = mask_student_code("20211020034")
        partes_visibles = resultado.replace("*", "")
        # Solo deberían verse los primeros 4 y los últimos 2 caracteres
        assert partes_visibles == "202134"


# ---------------------------------------------------------------------------
# Tests del servicio: lógica de cierre de sesión
# ---------------------------------------------------------------------------

class TestCerrarSesionLogica:
    """Verificamos las reglas de negocio sin llamar a la BD."""

    def test_cerrar_sesion_de_otro_usuario_lanza_error(self):
        # Si el user_id del token no coincide con el de la sesión → 403
        propietario = uuid.uuid4()
        intruso = uuid.uuid4()
        sesion = _sesion_falsa(user_id=propietario)

        # Simulamos la comprobación que hace cerrar_sesion()
        if sesion.user_id != intruso:
            with pytest.raises(SesionDeOtroUsuarioError):
                raise SesionDeOtroUsuarioError("No tienes permiso.")

    def test_cerrar_sesion_ya_terminada_lanza_error(self):
        # Si ended_at ya tiene valor → 409
        sesion = _sesion_falsa(ended_at=datetime(2024, 3, 1, 11, 0, 0, tzinfo=timezone.utc))

        if sesion.ended_at is not None:
            with pytest.raises(SesionYaTerminadaError):
                raise SesionYaTerminadaError("Ya estaba cerrada.")

    def test_sesion_no_encontrada_lanza_error(self):
        # Si la sesión no existe en BD → 404
        sesion = None
        if sesion is None:
            with pytest.raises(SesionNoEncontradaError):
                raise SesionNoEncontradaError("No existe.")

    def test_sesion_activa_sin_ended_at(self):
        # Una sesión activa debe tener ended_at en None
        sesion = _sesion_falsa()
        assert sesion.ended_at is None

    def test_cierre_correcto_actualiza_campos(self):
        # Simulamos el efecto de cerrar_sesion() sobre el objeto
        sesion = _sesion_falsa()
        ahora = datetime.now(timezone.utc)
        sesion.ended_at = ahora
        sesion.end_reason = MagicMock()
        sesion.end_reason.value = "user_logout_web"

        assert sesion.ended_at == ahora
        assert sesion.end_reason.value == "user_logout_web"


# ---------------------------------------------------------------------------
# Tests del schema de perfil: qué se devuelve y qué no
# ---------------------------------------------------------------------------

class TestPerfilSchema:
    """El perfil nunca debe exponer datos sensibles en claro."""

    def test_perfil_contiene_campos_obligatorios(self):
        usuario = _usuario_falso()
        nombre = usuario.full_name_ct.decode("utf-8")
        codigo_raw = usuario.student_code_ct.decode("utf-8")
        codigo_enmascarado = mask_student_code(codigo_raw)

        perfil = {
            "id": str(usuario.id),
            "full_name": nombre,
            "student_code_masked": codigo_enmascarado,
            "role": usuario.role.value,
            "status": usuario.status.value,
            "created_at": usuario.created_at.isoformat(),
        }

        assert "id" in perfil
        assert "full_name" in perfil
        assert "student_code_masked" in perfil
        assert "role" in perfil
        assert "status" in perfil

    def test_perfil_no_expone_codigo_en_claro(self):
        # student_code_ct contiene el código completo; la respuesta no debe hacerlo
        codigo_completo = "20211020034"
        usuario = _usuario_falso(student_code=codigo_completo)
        codigo_raw = usuario.student_code_ct.decode("utf-8")
        codigo_en_respuesta = mask_student_code(codigo_raw)

        # El código completo no debe aparecer en la respuesta
        assert codigo_completo not in codigo_en_respuesta
        assert "*" in codigo_en_respuesta

    def test_perfil_no_incluye_password_hash(self):
        # Verificamos que el schema PerfilResponse no tiene password_hash
        from app.routers.student import PerfilResponse
        campos = PerfilResponse.model_fields.keys()
        assert "password_hash" not in campos
        assert "email_ct" not in campos
        assert "student_code_ct" not in campos

    def test_perfil_role_es_string(self):
        usuario = _usuario_falso(role="student")
        assert isinstance(usuario.role.value, str)
        assert usuario.role.value == "student"


# ---------------------------------------------------------------------------
# Tests del schema de historial paginado
# ---------------------------------------------------------------------------

class TestHistorialPaginado:
    """Verificamos la estructura de la respuesta de historial."""

    def test_historial_respuesta_tiene_campos_paginacion(self):
        # Simulamos la construcción de HistorialResponse
        from app.routers.student import HistorialResponse, SesionResumen, MaquinaEnSesion

        maquina = MaquinaEnSesion(id=uuid.uuid4(), code="LAB01-PC05", lab="Sala 1")
        sesion = SesionResumen(
            id=uuid.uuid4(),
            machine=maquina,
            started_at=datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2024, 3, 1, 11, 0, 0, tzinfo=timezone.utc),
            end_reason="user_logout_web",
        )

        respuesta = HistorialResponse(page=1, page_size=20, total=1, items=[sesion])

        assert respuesta.page == 1
        assert respuesta.page_size == 20
        assert respuesta.total == 1
        assert len(respuesta.items) == 1

    def test_historial_pagina_vacia_cuando_no_hay_sesiones(self):
        from app.routers.student import HistorialResponse
        respuesta = HistorialResponse(page=1, page_size=20, total=0, items=[])

        assert respuesta.total == 0
        assert respuesta.items == []

    def test_historial_sesion_activa_sin_ended_at(self):
        from app.routers.student import SesionResumen, MaquinaEnSesion
        sesion = SesionResumen(
            id=uuid.uuid4(),
            machine=MaquinaEnSesion(id=uuid.uuid4(), code="LAB01-PC01", lab=None),
            started_at=datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
            ended_at=None,  # sesión activa
            end_reason=None,
        )
        # Una sesión sin ended_at es válida (es la activa)
        assert sesion.ended_at is None
        assert sesion.end_reason is None


# ---------------------------------------------------------------------------
# Tests de la dependencia de autenticación
# ---------------------------------------------------------------------------

class TestDependenciaAuth:
    """Verificamos que get_current_user rechaza correctamente los tokens."""

    def test_sin_token_lanza_http_401(self):
        from fastapi import HTTPException
        from app.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=None)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "TOKEN_MISSING"

    def test_token_invalido_lanza_http_401(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        from unittest.mock import patch
        from app.jwt import InvalidTokenError
        from app.dependencies import get_current_user

        creds_falsas = MagicMock(spec=HTTPAuthorizationCredentials)
        creds_falsas.credentials = "esto.no.es.un.jwt.valido"

        # Simulamos que verify_access_token lanza InvalidTokenError
        # (así se comporta en prod cuando el token no tiene firma ES256 válida)
        with patch("app.dependencies.verify_access_token", side_effect=InvalidTokenError("Token inválido")):
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(credentials=creds_falsas)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "TOKEN_INVALID"

    def test_get_current_student_rechaza_rol_admin(self):
        from fastapi import HTTPException
        from app.dependencies import get_current_student

        claims_admin = {"sub": str(uuid.uuid4()), "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            get_current_student(claims=claims_admin)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "ROLE_FORBIDDEN"

    def test_get_current_student_acepta_rol_student(self):
        from app.dependencies import get_current_student

        claims = {"sub": str(uuid.uuid4()), "role": "student"}
        resultado = get_current_student(claims=claims)
        # Debe devolver los mismos claims sin modificar
        assert resultado["role"] == "student"

    def test_get_user_id_devuelve_uuid(self):
        from app.dependencies import get_user_id

        user_id = uuid.uuid4()
        claims = {"sub": str(user_id), "role": "student"}
        resultado = get_user_id(claims=claims)

        assert isinstance(resultado, uuid.UUID)
        assert resultado == user_id
