# Base de datos — Neon (OPS-02)

Dos proyectos Neon independientes, uno por entorno: `internet-cafe-dev` e `internet-cafe-prod`,
con el cómputo fijado en **0,25 CU** (mín = máx).

## 1. Crear los proyectos
```bash
python -m tools.neon_projects --env dev            # dry-run: imprime el cuerpo, no usa la red
NEON_API_KEY=... python -m tools.neon_projects --env dev --apply
```
La clave de API se pasa solo por entorno; el script no la imprime.

## 2. Roles (una vez por proyecto, como dueño del proyecto Neon)
```bash
psql "$NEON_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -v migrator_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -v app_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -f db/bootstrap_roles.sql
```
Guarda las contraseñas en el gestor de secretos al generarlas (no se pueden leer después).
Mínimo 32 caracteres; el script aborta si faltan o son cortas. Es idempotente: volver a correrlo rota las contraseñas.
Nota: `ALTER ROLE ... PASSWORD` puede aparecer en los logs del servidor; rota las contraseñas si los logs son accesibles.

| Rol | Uso | Privilegios |
|---|---|---|
| `svc_migrator` | Alembic (CI) | DDL en el esquema `app`; `statement_timeout` 120 s |
| `svc_app` | API | SELECT, INSERT, UPDATE (también en tablas futuras); sin DELETE/TRUNCATE/DDL; `statement_timeout` 5 s |

### 2b. Un rol por actor (ST-SEC-03, SRS §12.8)
Se crean con el mismo script si llegan sus cuatro contraseñas (si falta alguna, el script aborta;
si no llega ninguna, solo se crean `svc_migrator` y `svc_app`):
```bash
psql "$NEON_ADMIN_URL" -v ON_ERROR_STOP=1 \
  -v migrator_password="$SVC_MIGRATOR_PASSWORD" -v app_password="$SVC_APP_PASSWORD" \
  -v web_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -v machine_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -v admin_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -v jobs_password="$(openssl rand -base64 36 | tr -d '\n')" \
  -f db/bootstrap_roles.sql
```
El script solo crea el rol, sus límites, `CONNECT` y `USAGE` en `app`. Los GRANT de cada tabla
están en la migración `9b4e6d2a8c15` (y cada tabla nueva tiene que concederse en su migración):

| Rol | Variable en Render | Uso | Lo que NO puede |
|---|---|---|---|
| `svc_web` | `DATABASE_URL_WEB` | `/auth`, `/me`, `/scan`, salud | DELETE; leer la clave o la credencial de los equipos |
| `svc_machine` | `DATABASE_URL_MACHINE` | `/machine/*` | DELETE; leer de `users` algo distinto de id, nombre y código |
| `svc_admin` | `DATABASE_URL_ADMIN` | `/admin/*` | DELETE; leer o cambiar `password_hash` |
| `svc_jobs` | `DATABASE_URL_JOBS` | Barrido de inactividad | DELETE fuera de las tablas efímeras; leer `users` |

Ninguno puede hacer DDL ni TRUNCATE, y en `audit_log` solo insertan (`svc_admin` también lee).
Cada variable es opcional: el actor que no la tenga usa `DATABASE_URL`, así que se pueden
activar de a una. **Orden:** primero crear los roles y después desplegar (el deploy corre
`alembic upgrade head`, que les da los GRANT). Si los roles se crean cuando la migración ya
corrió, sus GRANT se aplican con `alembic downgrade 7c2d4f9a1b3e && alembic upgrade head`.

### 2c. Row-Level Security (ST-SEC-05, SRS §12.8)
La migración `c3a7e5f1d902` activa RLS en `access_sessions`, `login_challenges`, `refresh_tokens`
y `machines` (en esta solo se limita el UPDATE). `svc_web` y `svc_machine` solo ven las filas que
corresponden a las variables `app.*` que la API fija tras autenticar (`fijar_contexto_rls` en
`app/database.py`); **sin variables ven cero filas** (falla cerrada):

| Variable | La fija | Deja ver |
|---|---|---|
| `app.user_id` | `require_user`, login, renovación | Sesiones y refresh tokens del usuario |
| `app.machine_id` | `require_machine`, enrolamiento | Sesiones y retos del equipo; actualizar su fila |
| `app.machine_user_id` | Sesión actual del equipo | Historial del estudiante sentado en ese equipo |
| `app.refresh_hash` | Renovar / cerrar sesión | Solo el refresh token presentado |
| `app.challenge_hash` | Vista previa y claim del QR | Solo el reto del QR escaneado |
| `app.claim_machine_id` | Claim del QR | Sesiones y retos del equipo del QR (equipo ocupado) |

`svc_admin`, `svc_jobs` y `svc_app` (el rol único de transición) no tienen restricción; el dueño
de las tablas y los superusuarios no pasan por RLS. Una tabla nueva con dueño necesita sus
políticas en su migración.

## 3. Orden de despliegue
1. `bootstrap_roles.sql` → 2. `alembic upgrade head` con `DATABASE_URL_MIGRATOR` → 3. volver a correr el bootstrap (idempotente, reafirma privilegios).

La API usa `DATABASE_URL` con `svc_app`; `DATABASE_URL_MIGRATOR` no se define en el servidor de la API.
Se acepta la URL de Neon tal cual (`sslmode`, `channel_binding`): `app/db_url.py` la adapta a asyncpg.

## 4. Pruebas
`tests/unit/test_bootstrap_roles.py` y `tests/unit/test_st_sec03_roles_por_actor.py` corren siempre. Contra PostgreSQL real (opt-in):
`TEST_ROLES_ADMIN_URL=postgresql://postgres@localhost/internet_cafe_test_roles pytest tests/integration/test_roles_bootstrap.py`
(`tests/integration/test_st_sec03_privilegios_por_actor.py` prueba los cuatro roles y
`tests/integration/test_st_sec05_rls.py` el aislamiento por RLS, con la misma variable).
