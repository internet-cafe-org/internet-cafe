"""Camino feliz de la semilla de carga y las peticiones firmadas de Locust (BE-19a)."""

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import obtener_base_datos
from app.main import app
from app.models import Lab, Machine, MachineStatus
from tools.carga.datos import (
    CUERPO_LATIDO,
    LATIDO,
    RETO_EN_ESPERA,
    SALA,
    cabeceras_firmadas,
    cargar_o_crear_claves,
    leer_claves,
    sembrar_equipos,
)


async def test_carga_con_identidades_firmadas(sesiones, tmp_path, monkeypatch):
    archivo = tmp_path / ".env.locust.json"
    await sembrar_equipos(sesiones, cargar_o_crear_claves(archivo))
    await sembrar_equipos(sesiones, cargar_o_crear_claves(archivo))
    claves = leer_claves(archivo)

    async with sesiones() as db:
        equipos = (await db.scalars(select(Machine).order_by(Machine.code))).all()
        assert len(equipos) == 300
        assert len({equipo.key_thumbprint for equipo in equipos}) == 300
        assert all(equipo.status == MachineStatus.active for equipo in equipos)
        assert all("d" not in equipo.public_key_jwk for equipo in equipos)
        assert (await db.scalars(select(Lab.name))).all() == [SALA]

    async def obtener_sesion():
        async with sesiones() as db:
            yield db

    origen = "http://test"
    monkeypatch.setitem(app.dependency_overrides, obtener_base_datos, obtener_sesion)
    monkeypatch.setattr(settings, "machine_auth_mode", "signature")
    monkeypatch.setattr(settings, "public_api_base_url", origen)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=origen) as cliente:
        latido = await cliente.post(
            LATIDO, headers=cabeceras_firmadas(claves[0], "POST", origen + LATIDO, CUERPO_LATIDO),
            content=CUERPO_LATIDO,
        )
        assert latido.status_code == 200
        assert latido.json()["session_status"] == "none"

        ruta = f"{RETO_EN_ESPERA}?timeout=1"
        espera = await cliente.get(ruta, headers=cabeceras_firmadas(claves[-1], "GET", origen + ruta))
        assert espera.status_code == 200
        assert espera.json() == {"status": "waiting"}

    async with sesiones() as db:
        assert (await db.get(Machine, equipos[0].id)).last_seen_at is not None
