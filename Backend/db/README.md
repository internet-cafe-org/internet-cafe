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

## 3. Orden de despliegue
1. `bootstrap_roles.sql` → 2. `alembic upgrade head` con `DATABASE_URL_MIGRATOR` → 3. volver a correr el bootstrap (idempotente, reafirma privilegios).

La API usa `DATABASE_URL` con `svc_app`; `DATABASE_URL_MIGRATOR` no se define en el servidor de la API.
Se acepta la URL de Neon tal cual (`sslmode`, `channel_binding`): `app/db_url.py` la adapta a asyncpg.

## 4. Pruebas
`tests/unit/test_bootstrap_roles.py` corre siempre. Contra PostgreSQL real (opt-in):
`TEST_ROLES_ADMIN_URL=postgresql://postgres@localhost/internet_cafe_test_roles pytest tests/integration/test_roles_bootstrap.py`
