# Despliegue en dev (OPS-11)

La API de dev corre en Render y la base en Neon (`internet-cafe-dev`). La web está en Vercel
y despliega sola con cada push (OPS-04). Este documento cubre los tres workflows del
environment `dev` de GitHub.

| Workflow | Cuándo corre | Qué hace |
|---|---|---|
| `deploy-dev` | Cada push a `main` | Cabeza única de Alembic → `alembic upgrade head` con `svc_migrator` → deploy hook de Render → prueba de humo |
| `dev-seed` | A mano (Actions → dev-seed → Run workflow) | Semilla idempotente: administrador, salas, equipos y, si se piden, códigos de enrolamiento |
| `dev-reset` | A mano, escribiendo `dev` para confirmar | Vacía el esquema `app` → `alembic upgrade head` → `dev-seed` |

Los tres comparten el grupo de concurrencia `dev-db`: nunca corren dos a la vez sobre la base,
y el que está corriendo no se cancela.

## Secretos y variables del environment `dev`

Los carga el líder de Seguridad y Testing en *Settings → Environments → dev*. No van en el
repo ni en `.env` versionados, y los workflows no los imprimen.

| Nombre | Tipo | Valor |
|---|---|---|
| `DATABASE_URL_MIGRATOR` | secret | URL de Neon dev con el rol `svc_migrator` (OPS-02) |
| `RENDER_DEPLOY_HOOK_URL` | secret | Deploy hook del servicio de Render dev (OPS-03) |
| `DEV_BLIND_INDEX_KEY` | secret | La misma `BLIND_INDEX_KEY` que tiene el servicio de Render dev |
| `DEV_ADMIN_PASSWORD` | secret | Contraseña del administrador de dev (de 10 a 128 caracteres) |
| `DEV_API_URL` | variable | URL pública de la API en Render, sin `/` final |
| `DEV_WEB_URL` | variable (opcional) | URL de la web en Vercel; si está, el humo también la prueba |
| `DEV_ADMIN_EMAIL` | variable (opcional) | Correo del administrador de dev; por defecto `admin@dev.invalid` |
| `DEV_ESPERA_DEPLOY_S` | variable (opcional) | Segundos de espera antes del humo; por defecto 420 |

En Render, el servicio de dev debe desplegar la rama `main` con el auto-deploy apagado
(OPS-03): solo despliega cuando lo pide el pipeline, después de migrar.

## Pipeline `deploy-dev`

1. **Cabeza única:** falla si `alembic heads` devuelve más de una cabeza.
2. **Migración:** `alembic upgrade head` con `DATABASE_URL_MIGRATOR`.
3. **Deploy hook:** pide a Render desplegar el último commit de `main`.
4. **Humo:** espera `DEV_ESPERA_DEPLOY_S` y luego exige 200 en `/healthz` y `/readyz` (y en la
   web si hay `DEV_WEB_URL`), con hasta 10 intentos cada 30 s por el arranque en frío.

Como se migra **antes** de desplegar, durante unos minutos la versión anterior de la API
corre sobre el esquema nuevo. Las migraciones deben ser compatibles hacia atrás: agregar
columnas con valor por defecto o que acepten nulos, y borrar o renombrar en un PR posterior.

**Limitación conocida:** el deploy hook responde al instante y Render no informa cuándo
termina sin una clave de su API. Por eso el humo espera un tiempo fijo. Si un build de Render
falla, la versión anterior sigue respondiendo y el humo puede quedar en verde: revisa el
estado del deploy en el panel de Render cuando el pipeline termine.

## Semilla (`dev-seed`)

`tools/seed_dev.py` (QA-02a) deja en dev:

- el administrador (`DEV_ADMIN_EMAIL`), activo, con la contraseña de `DEV_ADMIN_PASSWORD`;
- `Sala Dev 1` con los equipos `DEV-S1-PC01` a `DEV-S1-PC03`, pendientes de enrolar;
- N códigos de enrolamiento (input `codigos`, de 0 a 50), válidos por 24 h.

Correrla otra vez no duplica nada: reafirma el administrador y solo crea lo que falta. Los
códigos sí se generan nuevos en cada ejecución. En la base solo queda su SHA-256.

**Códigos de enrolamiento:** no aparecen en el log. Salen en el artefacto
`codigos-enrolamiento-dev` (se borra en 1 día), cifrado con la contraseña del administrador
de dev. Para leerlo, descárgalo desde la ejecución y corre:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in codigos.txt.enc -out codigos.txt
# pide la contraseña: la de DEV_ADMIN_PASSWORD
```

Cada línea trae el código del equipo y su código de enrolamiento. Borra el archivo al terminar.

En local, contra una base propia:

```bash
cd Backend
APP_ENV=dev BLIND_INDEX_KEY=... SEED_ADMIN_PASSWORD=... python -m tools.seed_dev --codigos 2 --salida-codigos codigos.txt
```

## Reset (`dev-reset`)

`tools/reset_dev.py` borra, con el rol `svc_migrator`, las tablas (incluida `alembic_version`)
y los tipos enum del esquema `app` cuyo dueño es ese rol. No toca el esquema, los roles ni los
privilegios de `db/bootstrap_roles.sql`. Después el workflow migra y siembra.

No usa `alembic downgrade base` porque el `downgrade()` de la migración inicial no borra los
tipos enum y el `upgrade` siguiente fallaría al recrearlos.

Úsalo cuando cambie el formato de los datos guardados (por ejemplo, cuando SEC-06 active el
cifrado real de la interfaz `pii`). **Borra todos los datos de dev.**
