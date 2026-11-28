# Reporte de la prueba de carga en dev (BE-19b)

Historia HU-39. Mide si una instancia de la API soporta el piloto: 300 equipos con latido y
long-poll (SRS §6.1, RNF-REN-03 y RNF-REN-04). La herramienta es la de BE-19a
(`Backend/tools/carga`, sección "Preparación de la carga de dev" del README de Backend).

## 1. Resumen

| Requisito | Meta | Resultado en dev | Estado |
|---|---|---|---|
| RNF-REN-04 | 300 equipos concurrentes sin 5xx ni agotamiento de conexiones | 1 respuesta 520 y 312 errores de conexión (6,4 %) a partir del minuto 3 | **No cumple** |
| RNF-REN-03 | p95 < 300 ms en lecturas, en caliente | `/readyz` p95 1,14 s; latido p95 2,1 s | **No cumple** |
| Long-poll | La espera del QR vuelve a los 25 s sin errores | p50 25 s, p95 27 s; 25 fallas de 3348 (0,7 %) | Cumple con reservas |
| RNF-REN-01 | p95 de `POST /scan/claim` < 500 ms con 50 claims/min | No medido: el escenario de BE-19a no incluye claims | Pendiente |

**Conclusión:** con el plan gratuito de Render (0,15 CPU y 512 MB), la API aguanta los primeros
3 minutos con 300 equipos, pero después pierde conexiones en las ráfagas de latidos.
**`render.prod.yaml` también usa `plan: free`**, así que producción tendría el mismo límite.

## 2. Entorno y parámetros

| Dato | Valor |
|---|---|
| Fecha | vie 27/11/2026, 23:48 a 23:54 (hora de Colombia) |
| API | Render dev `internet-cafe-tq03.onrender.com`, commit `664a3cb` de `develop`, plan free (0,15 CPU, 512 MB, 1 worker de uvicorn) |
| Base | Neon dev (PostgreSQL 18), migrada a `4dfc8356302b` |
| Autenticación de equipos | `MACHINE_AUTH_MODE=signature` (firma RFC 9421 en cada petición) |
| Rate limit | Apagado durante la prueba (`RATE_LIMIT_ENABLED=false`) y encendido al terminar |
| Cliente | Locust 2.47.0 en un PC con Windows 11, un solo proceso |
| Carga | 300 usuarios (`DEV-LOCUST-PC001` a `PC300`), 10 por segundo, 5 minutos |
| Comportamiento de cada usuario | Un latido al arrancar y uno cada 60 s; long-poll de 25 s continuo |

```powershell
python -m locust -f tools/carga/locustfile.py --headless `
  --host https://internet-cafe-tq03.onrender.com -u 300 -r 10 -t 5m `
  --stop-timeout 35 --csv "$env:TEMP\locust-dev"
```

## 3. Resultados

| Ruta | Peticiones | Fallas | p50 | p90 | p95 | p99 | Máx. |
|---|---|---|---|---|---|---|---|
| `GET /machine/challenges/wait` | 3348 | 25 (0,7 %) | 25,0 s | 27,0 s | 27,0 s | 27,0 s | 35,0 s |
| `POST /machine/heartbeat` | 1543 | 288 (18,7 %) | 0,69 s | 1,9 s | 2,1 s | 2,6 s | 4,2 s |
| Total | 4891 | 313 (6,4 %) | | | | | |

Durante la prueba se midió `GET /readyz` cada 10 s desde el mismo PC: 33 respuestas 200,
p50 0,39 s, p95 1,14 s, máximo 1,92 s.

### Cuándo aparecen las fallas

| Segundo de la prueba | Peticiones acumuladas | Fallas acumuladas |
|---|---|---|
| 0 a 185 | 2697 | 1 (un 520 a los 48 s) |
| 190 a 214 | 3324 | 236 |
| 242 a 250 | 3810 | 297 |
| Final | 4891 | 313 |

Los latidos se envían en oleadas: al subir 10 usuarios por segundo, los 300 latidos de cada
minuto caen en una ventana de unos 30 s. Las tres primeras oleadas pasaron sin errores; la cuarta
(desde los 190 s) perdió casi 240 latidos y la quinta, unos 60. Los errores son de conexión
(el cliente no recibe respuesta), no 5xx de la aplicación. El plan gratuito de Render no
muestra CPU ni memoria, así que no se pudo confirmar si la causa es CPU, memoria o el límite de
conexiones del proxy. Lo más probable es la CPU: cada latido verifica una firma ECDSA y escribe
en la base, con 0,15 CPU para todo el proceso.

## 4. Decisiones y siguientes pasos

1. **Plan de producción (PO y líder de Seguridad y Testing).** Con `plan: free` en
   `render.prod.yaml` no se cumple RNF-REN-04. Se recomienda un plan pago (Starter, 0,5 CPU)
   para el piloto y repetir esta prueba allí antes del congelamiento.
2. **Repartir los latidos (Desktop).** Agregar un desfase aleatorio de 0 a 60 s al primer latido
   evita que muchos equipos encendidos a la vez coincidan cada minuto.
3. **Claims (RNF-REN-01).** Falta un escenario con 50 `POST /scan/claim` por minuto; necesita
   usuarios web de prueba. Queda para una tarea aparte.
4. **Métricas.** En un plan pago, repetir la prueba mirando CPU y memoria para confirmar la causa.

## 5. Incidentes durante la prueba

- **Despliegue fallido por la variable.** `RATE_LIMIT_ENABLED` quedó escrita como `"False"` con
  comillas y salto de línea, y la API no arrancó (`bool_parsing` en `Settings`). Render siguió
  sirviendo la versión anterior con el límite encendido. El valor debe ser exactamente `false`
  o `true`. Se anotó en el README.
- **`tzdata` en Windows.** La semilla falló en Windows porque Python no trae la base de zonas
  horarias y `Settings` rechaza `CSV_TIMEZONE=America/Bogota`. Se agregó `tzdata` a
  `requirements.txt`; en Linux (Render) no fallaba.

## 6. Datos que quedan en dev

- La sala `Sala Dev Locust` y los 300 equipos `DEV-LOCUST-PC001` a `PC300` siguen en Neon dev
  para repetir la prueba con las mismas claves. Aparecen en el listado de equipos del admin.
- Para retirarlos, cada equipo se puede deshabilitar con `PATCH /admin/machines/{id}`
  (`{"status": "disabled"}`) o borrarse junto con la sala en un `dev-reset`.
- Los archivos CSV de Locust no se versionan: tienen solo rutas, tiempos y códigos HTTP.
