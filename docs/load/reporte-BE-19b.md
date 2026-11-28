# Reporte de prueba de carga — BE-19b

| Campo           | Valor                                      |
|-----------------|--------------------------------------------|
| Tarea           | BE-19b · Ejecutar carga y reporte          |
| Historia        | HU-39 · Prueba de carga, accesibilidad y pruebas en Windows |
| Fecha           | Jueves 26 de noviembre de 2026, 22:00–22:15 COT |
| Entorno         | dev (Render · `RATE_LIMIT_ENABLED=false`)  |
| Script          | `Backend/load/locustfile.py`               |
| Firmador        | RFC 9421 · `contracts/test-vectors/firmador_referencia.py` (SEC-08) |
| Dependencia     | BE-19a (datos y script de Locust)          |

---

## 1. Configuración de la prueba

```
locust -f Backend/load/locustfile.py \
       --headless -u 300 -r 10 --run-time 10m \
       --host https://internet-cafe-api.onrender.com
```

| Parámetro            | Valor                                   |
|---------------------|-----------------------------------------|
| Usuarios concurrentes| 300 equipos enrolados                  |
| Rampa de arranque   | 10 equipos / s (30 s hasta carga plena)|
| Duración            | 10 min                                  |
| Rate limit          | `RATE_LIMIT_ENABLED=false` (dev)        |
| Auth de equipo      | Firma RFC 9421 (`MACHINE_AUTH_MODE=signature`) |
| Endpoints bajo carga| `POST /machine/heartbeat` · `GET /machine/challenges/wait` |

---

## 2. Resultados

### 2.1 Resumen global

| Métrica                     | Valor       |
|-----------------------------|-------------|
| Peticiones totales          | 32 847      |
| Fallos                      | 0           |
| Tasa de error               | 0,00 %      |
| RPS promedio                | 54,7        |
| RPS pico                    | 61,2        |
| Duración efectiva de la prueba | 10 min   |

### 2.2 Por endpoint

| Endpoint                            | Peticiones | Fallos | p50 (ms) | p95 (ms) | p99 (ms) | Máx (ms) |
|-------------------------------------|-----------|--------|----------|----------|----------|----------|
| `POST /machine/heartbeat`           | 29 213    | 0      | 142      | 389      | 621      | 1 204    |
| `GET /machine/challenges/wait`      | 3 634     | 0      | 25 018   | 25 891   | 26 102   | 27 340   |

> **Nota sobre `/machine/challenges/wait`:** el servidor mantiene la conexión
> abierta hasta que llega un evento o expira el timeout de 25 s, por lo que la
> latencia registrada refleja el tiempo de espera del long-poll, no la latencia
> de red. El valor de p99 de 26 s está dentro del rango esperado.

### 2.3 Uso de recursos del servidor (Render dev — plan Starter)

| Recurso   | Pico observado | Límite del plan |
|-----------|---------------|-----------------|
| CPU       | 68 %          | 100 %           |
| RAM       | 312 MB        | 512 MB          |
| Conexiones DB (Neon) | 42   | 100 (plan Free) |

---

## 3. Observaciones

- **Sin errores 5xx ni 429:** los 300 equipos completaron el ciclo de latido /
  long-poll durante los 10 min sin ningún fallo.  El rate limit estaba apagado
  (`RATE_LIMIT_ENABLED=false`), por lo que esta cifra no es representativa de
  producción.
- **Latencia del heartbeat:** el p95 de 389 ms está por debajo del umbral de
  1 s que fija el SRS (§15.3, RNF-REN-02).  El pico de 1 204 ms se produjo
  durante la rampa de arranque (primeros 30 s) y no volvió a aparecer.
- **Long-poll:** el comportamiento es el esperado; la conexión se mantiene ~25 s
  y el servidor responde `{"status":"waiting"}`.  No se detectaron fugas de
  conexión ni acumulación de workers bloqueados.
- **Conexiones de BD:** el pico de 42 conexiones simultáneas está lejos del
  límite de 100 de Neon Free.  El pool de la API (5 conexiones, `DB_POOL_SIZE`)
  no se saturó gracias al multiplexado de SQLAlchemy async.
- **Memoria:** la RAM del worker de Render se mantuvo estable en ~312 MB pico
  (sin crecimiento sostenido), lo que descarta fugas en la gestión de eventos
  del long-poll.

---

## 4. Veredicto

> ✅ **La API de dev soporta 300 equipos con latido y long-poll concurrentes
> sin errores y con latencias dentro de los objetivos del SRS.**

---

## 5. Acciones derivadas

| # | Acción                                                        | Responsable | Estado    |
|---|---------------------------------------------------------------|-------------|-----------|
| 1 | Reactivar `RATE_LIMIT_ENABLED=true` en dev                   | Backend     | ✅ Hecho  |
| 2 | Revisar el pico de latencia en la rampa (1 204 ms, heartbeat) | Backend     | ⚠️ Monitorear en la siguiente prueba |
| 3 | Validar el comportamiento con rate limit activo antes de producción | Backend / Testing | Pendiente (QA-15) |

---

## 6. Referencia

- Backlog: `docs/backlog/backlog-mvp.md` §11 (HU-39, BE-19a, BE-19b)
- Script: `Backend/load/locustfile.py`
- Firmador: `contracts/test-vectors/firmador_referencia.py` (SEC-08)
- Configuración de Render dev: `docs/ops/despliegue-dev.md`
