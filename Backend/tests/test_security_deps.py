# -*- coding: utf-8 -*-
from datetime import timedelta
import uuid as _uuid
import pytest
import httpx
from fastapi import Depends, FastAPI
from app.database import obtener_base_datos
from app.jwt import create_access_token
from app.models import Machine, MachineStatus
from app.security.dependencies import require_admin, require_machine, require_user, hash_machine_credential

@pytest.fixture
def jwt_keys(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from app.config import settings
    clave = ec.generate_private_key(ec.SECP256R1())
    privada = clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    publica = clave.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(settings, 'jwt_private_key', privada)
    monkeypatch.setattr(settings, 'jwt_public_key', publica)

def _crear_actor(role: str) -> dict:
    from app.jwt import create_access_token
    actor_id = _uuid.uuid4()
    token = create_access_token(subject=str(actor_id), role=role)
    return {'id': actor_id, 'token': token, 'headers': {'Authorization': f'Bearer {token}'}}

@pytest.fixture
def student(jwt_keys): 
    return _crear_actor('student')

@pytest.fixture
def admin(jwt_keys): 
    return _crear_actor('admin')

@pytest.fixture
def equipo():
    credencial = 'credencial-provisional-de-prueba'
    machine = Machine(id=_uuid.uuid4(), code='LAB-TEST-01', status=MachineStatus.active, key_thumbprint=hash_machine_credential(credencial))
    return {'machine': machine, 'credential': credencial, 'headers': {'X-Machine-Code': machine.code, 'X-Machine-Key': credencial}}

class _Resultado:
    def __init__(self, valor): self._valor = valor
    def scalar_one_or_none(self): return self._valor

class _BaseFalsa:
    def __init__(self, machine): self._machine = machine
    async def execute(self, _consulta): return _Resultado(self._machine)

def _crear_app(machine=None) -> FastAPI:
    app = FastAPI()
    @app.get('/usuario')
    async def usuario(u=Depends(require_user)): return {'id': str(u.id), 'role': u.role.value}
    @app.get('/admin')
    async def solo_admin(u=Depends(require_admin)): return {'id': str(u.id)}
    @app.get('/equipo')
    async def equipo(m=Depends(require_machine)): return {'code': m.code}
    app.dependency_overrides[obtener_base_datos] = lambda: _BaseFalsa(machine)
    return app

def _cliente(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

@pytest.mark.asyncio
async def test_require_user_camino_feliz(student):
    async with _cliente(_crear_app()) as c: r = await c.get('/usuario', headers=student['headers'])
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_require_user_sin_token_da_401(jwt_keys):
    async with _cliente(_crear_app()) as c: r = await c.get('/usuario')
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_require_user_token_basura_da_401(jwt_keys):
    async with _cliente(_crear_app()) as c: r = await c.get('/usuario', headers={'Authorization': 'Bearer basura'})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_require_admin_camino_feliz(admin):
    async with _cliente(_crear_app()) as c: r = await c.get('/admin', headers=admin['headers'])
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_require_admin_con_rol_estudiante_da_403(student):
    async with _cliente(_crear_app()) as c: r = await c.get('/admin', headers=student['headers'])
    assert r.status_code == 403

@pytest.mark.asyncio
async def test_require_machine_camino_feliz(equipo):
    async with _cliente(_crear_app(machine=equipo['machine'])) as c: r = await c.get('/equipo', headers=equipo['headers'])
    assert r.status_code == 200
