# Runbook de operaciones — Backend (OPS-03 · Sprint 2)

> **Dueño del documento:** equipo Backend  
> **Revisado por:** Scrum Master antes de cada review  
> **Última actualización:** 2026-11-09

Este runbook describe cómo montar, actualizar y depurar el backend en el entorno
dev de Render. Para el flujo de despliegue automatizado ver también
[`docs/ops/despliegue-dev.md`](./despliegue-dev.md).

---

## 1. Generar las llaves criptográficas de dev

Antes de crear el servicio en Render hay que tener las llaves listas.
Ejecutar **una sola vez** desde la raíz de `Backend/`:

```bash
# Dentro del directorio Backend/
python -m tools.generate_keys
```

Esto crea la carpeta `Backend/tools/keys/` (ignorada por git) con:

| Archivo | Uso |
|---|---|
| `jwt_es256_private.pem` | Firma de tokens JWT |
| `jwt_es256_public.pem` | Verificación de tokens JWT |
| `data_enc_keys.json` | Anillo de llaves AES-256-GCM para cifrado de datos |
| `blind_index_key.txt` | Llave HMAC-SHA256 para índices ciegos |
| `keys.env` | Fragmento de referencia para cargar en Render |

> **Importante:** nunca subir estos archivos a git. El `.gitignore` ya los excluye,
> pero revisar con `git status` antes de hacer commit.

---

## 2. Crear el servicio en Render (Blueprint)

El `render.yaml` define el servicio completo. Para que Render lo aplique hay que
usar **Blueprint**, no "Web Service" individual:

1. Entrar a [https://dashboard.render.com](https://dashboard.render.com) con la
   cuenta del equipo Backend.
2. Clic en **New → Blueprint**.
3. Conectar el repositorio `internet-cafe-org/internet-cafe`.
4. Render detecta el `render.yaml` y muestra el servicio `internet-cafe-backend-dev`.
5. Verificar que **Auto-Deploy** aparece como **Off**.
6. Clic en **Apply**.

> **Atención:** los cambios realizados manualmente en el dashboard de Render
> (variables, región, plan) se **sobrescriben** en el siguiente sync del Blueprint.
> Siempre editar el `render.yaml` en el repositorio y hacer push.

---

## 3. Cargar los secretos en Render

Ir a **Dashboard → internet-cafe-backend-dev → Environment**.

Agregar las siguientes variables de entorno con los valores reales.

| Variable | Cómo obtenerla |
|---|---|
| `DATABASE_URL` | URL de conexión de Neon **proyecto `internet-cafe-dev`** (ver §6). Usar el rol `svc_app` (OPS-02), **no** el rol dueño del proyecto. Formato: `postgresql://svc_app:<pwd>@<host>/<db>?sslmode=require` |
| `SECRET_KEY` | Render puede generarla automáticamente (`generateValue: true` en el YAML) o manualmente con `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_PRIVATE_KEY` | Contenido de `jwt_es256_private.pem`. **Pegar con saltos de línea reales** en el campo de Render (no con `\n` escapados). Usar el botón multiline del editor de variables. |
| `JWT_PUBLIC_KEY` | Contenido de `jwt_es256_public.pem` (saltos de línea reales, igual que la clave privada) |
| `DATA_ENC_KEYS` | JSON de `data_enc_keys.json`, ej. `{"1": "<64 hex chars>"}` |
| `BLIND_INDEX_KEY` | Contenido de `blind_index_key.txt` (sin salto de línea al final) |

> **Por qué saltos de línea reales para las claves PEM:**
> PyJWT necesita el formato PEM estándar con saltos de línea reales para parsear
> la curva EC. Si se pegan con `\n` literales (backslash + n), la firma ES256 falla.
> `_load_key_content` en `app/jwt.py` convierte `\n` literales a reales como
> respaldo, pero lo más seguro es pegar el PEM multiline directamente en Render.

---

## 4. Crear el deploy hook en Render

El pipeline `deploy-dev` dispara el despliegue mediante un deploy hook en lugar
de un push directo. Hay que crearlo una sola vez:

1. **Dashboard → internet-cafe-backend-dev → Settings → Deploy Hook**.
2. Clic en **Create Deploy Hook** y copiar la URL generada.
3. Ir a **GitHub → Settings → Secrets and variables → Actions → Environment: dev**.
4. Crear el secreto `RENDER_DEPLOY_HOOK_URL` con la URL copiada en el paso anterior.

---

## 5. Desplegar una nueva versión

El auto-deploy está apagado. El despliegue lo hace el pipeline `deploy-dev`
automáticamente tras fusionar a `main` (ver `despliegue-dev.md`):

1. El PR se aprueba y fusiona a `develop`.
2. `develop` se fusiona a `main` al cierre del sprint.
3. El workflow `deploy-dev.yml` ejecuta las migraciones de BD y luego
   dispara el deploy hook `RENDER_DEPLOY_HOOK_URL`.
4. Render descarga la imagen Docker desde la rama `main` y la despliega.
5. El pipeline verifica `/healthz` y `/readyz` como humo post-deploy.

> **No usar** "Manual Deploy" desde el dashboard: el pipeline de migración
> debe correr **antes** del deploy para evitar errores de esquema en prod.
> En caso de emergencia usar el deploy hook directamente con `curl`.

---

## 6. Ambientes Neon (dev y prod son proyectos separados)

Neon organiza los ambientes como **proyectos independientes**, no como ramas
dentro del mismo proyecto:

| Proyecto Neon | Ambiente | Uso |
|---|---|---|
| `internet-cafe-dev` | dev | Render dev, pipeline CI |
| `internet-cafe-prod` | prod | Render prod (OPS-08) |

La `DATABASE_URL` del servicio dev debe apuntar a **`internet-cafe-dev`**,
usando el rol `svc_app` creado en OPS-02 (mínimo privilegio: solo SELECT,
INSERT, UPDATE, DELETE; sin CREATE TABLE ni DROP).

---

## 7. Verificar que el servicio está vivo

Una vez que el deploy termina (estado "Live"):

```bash
# Reemplazar <URL> con la URL asignada por Render
curl https://<URL>/healthz
# Respuesta esperada: {"status":"ok","service":"backend"}

curl https://<URL>/readyz
# Respuesta esperada: {"status":"ready","database":"connected"}
```

- `/healthz` es el `healthCheckPath` de Render: lo llama automáticamente para
  monitorear el contenedor.
- `/readyz` lo verifica el pipeline `deploy-dev` como humo post-deploy; Render
  no lo llama directamente.

Si `/readyz` devuelve 503, el problema es la `DATABASE_URL`. Revisar en el
proyecto `internet-cafe-dev` de Neon que esté activo y que el rol `svc_app`
tenga los permisos correctos.

---

## 8. Ver los logs

En el dashboard de Render: **internet-cafe-backend-dev → Logs**.

Los logs están en formato JSON (ver `app/logger.py`). Para filtrar errores:

```
# En la barra de búsqueda de Render Logs
"level":"ERROR"
```

No deben aparecer valores como correos, identificaciones ni llaves en los logs.
Si aparecen, es un defecto crítico: abrir un issue `tipo:defecto` con severidad
`Crítica` inmediatamente.

---

## 9. Escalar o cambiar el plan

El servicio dev corre con `plan: free` y `--workers 1`. Si hay que hacer pruebas
de carga (BE-19a, sprint 4), cambiar temporalmente a `plan: starter` **desde el
YAML** (no desde el dashboard, para que no se sobreescriba en el siguiente sync
del Blueprint).

---

## 10. Acceso de emergencia

El PO tiene acceso de respaldo a la cuenta de Render del equipo. Las credenciales
están en el gestor de contraseñas compartido del equipo. Para saber dónde están,
preguntar en el canal privado `#ops-credenciales` — ahí solo se indica la
ubicación, **no** se comparten las credenciales directamente por chat.
