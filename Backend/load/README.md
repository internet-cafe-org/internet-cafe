# Prueba de carga — BE-19a / BE-19b

Simula **300 equipos enrolados** que ejecutan latido (`POST /machine/heartbeat`)
y long-poll (`GET /machine/challenges/wait`) en paralelo contra el entorno **dev**,
con `RATE_LIMIT_ENABLED=false`.

## Requisitos

```
pip install "locust>=2.29" cryptography
```

> Las demás dependencias del Backend (`cryptography`) ya están en el venv.

## Pasos

### 1. Preparar los datos de los equipos (BE-19a)

```bash
# Desde la raíz del repo, con el .env de dev cargado:
python -m Backend.load.prepare_machines \
       --out Backend/load/machines.json \
       --limite 300
```

El archivo `machines.json` **no se sube al repo** (`.gitignore`).

### 2. Apagar el rate limit en dev

Añadir (o verificar) en el entorno de Render dev:

```
RATE_LIMIT_ENABLED=false
```

### 3. Ejecutar la carga (BE-19b — jueves 26 en la noche)

```bash
locust -f Backend/load/locustfile.py \
       --headless -u 300 -r 10 --run-time 10m \
       --host https://<api-dev>.onrender.com \
       --html Backend/load/reporte-carga.html \
       --csv  Backend/load/reporte-carga
```

| Parámetro    | Valor    | Significado                               |
|-------------|----------|-------------------------------------------|
| `-u 300`    | 300      | Usuarios concurrentes (equipos)           |
| `-r 10`     | 10/s     | Rampa de arranque (10 equipos por segundo)|
| `--run-time`| 10 min   | Duración de la prueba                     |

### 4. Reactivar el rate limit

```
RATE_LIMIT_ENABLED=true
```

## Artefactos de salida

| Archivo                        | Descripción                              |
|-------------------------------|------------------------------------------|
| `reporte-carga.html`          | Informe interactivo de Locust            |
| `reporte-carga_stats.csv`     | Estadísticas por endpoint                |
| `reporte-carga_failures.csv`  | Detalle de fallos                        |
| `reporte-carga_stats_history.csv` | Serie temporal de RPS y latencias   |

> Estos archivos **no se suben al repo**.  El reporte en Markdown sí se sube
> (ver `docs/load/reporte-BE-19b.md`).
