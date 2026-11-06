# Runbook de operaciones — Backend (OPS-03 · Sprint 2)

> **Dueño del documento:** equipo Backend  
> **Revisado por:** Scrum Master antes de cada review  
> **Última actualización:** 2026-11-04

Este runbook describe cómo montar, actualizar y depurar el backend en el entorno
dev de Render. Cubrir producción queda pendiente para OPS-08.

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
| `keys.env` | Fragmento listo para pegar en Render |

> **Importante:** nunca subir estos archivos a git. El `.gitignore` ya los excluye,
> pero revisar con `git status` antes de hacer commit.

---

## 2. Crear el servicio en Render

1. Entrar a [https://dashboard.render.com](https://dashboard.render.com) con la
   cuenta del equipo Backend.
2. **New → Web Service → Connect a repository** → seleccionar `internet-cafe-org/internet-cafe`.
3. Render detecta el `render.yaml` automáticamente. Confirmar que carga el servicio
   `internet-cafe-backend-dev`.
4. Verificar que **Auto-Deploy** aparece como **Off** (ya viene así en el YAML).
5. Hacer clic en **Create Web Service**.

---

## 3. Cargar los secretos en Render

Ir a **Dashboard → internet-cafe-backend-dev → Environment**.

Agregar las siguientes variables usando los valores de `tools/keys/keys.env`:

| Variable | Cómo obtenerla |
|---|---|
| `DATABASE_URL` | URL de Neon dev creada en OPS-02 |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_PRIVATE_KEY` | Contenido de `jwt_es256_private.pem` (pegar con `\n` al final de cada línea) |
| `JWT_PUBLIC_KEY` | Contenido de `jwt_es256_public.pem` |
| `DATA_ENC_KEYS` | JSON de `data_enc_keys.json`, ej. `{"1": "<64 hex>"}` |
| `BLIND_INDEX_KEY` | Contenido de `blind_index_key.txt` (sin salto de línea) |

> **Consejo:** el archivo `keys.env` tiene las llaves JWT ya en formato de una
> sola línea con `\n` escapados, listo para pegar directamente en Render.

Tras guardar, hacer un **Manual Deploy** desde el dashboard.

---

## 4. Verificar que el servicio está vivo

Una vez que el deploy termina (estado "Live"):

```bash
# Reemplazar <URL> con la URL asignada por Render
curl https://<URL>/healthz
# Respuesta esperada: {"status":"ok","service":"backend"}

curl https://<URL>/readyz
# Respuesta esperada: {"status":"ready","database":"connected"}
```

Si `/readyz` devuelve 503, el problema es la `DATABASE_URL`. Revisar en Neon que
el proyecto dev esté activo y que la URL sea la de la rama `main` de Neon (no la
de producción).

---

## 5. Desplegar una nueva versión

El auto-deploy está apagado a propósito. Para desplegar:

1. Asegurarse de que el PR está fusionado en `develop` (o en `main` si ya pasó
   la review del sprint).
2. Ir a **Dashboard → internet-cafe-backend-dev → Manual Deploy → Deploy latest commit**.
3. Esperar a que el estado cambie a "Live".
4. Verificar `/healthz` y `/readyz`.

---

## 6. Ver los logs

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

## 7. Escalar o cambiar el plan

El servicio dev corre con `plan: free` y `--workers 1`. Si hay que hacer pruebas
de carga (BE-19a, sprint 4), cambiar temporalmente a `plan: starter` desde el
dashboard, **no** desde el YAML, para no afectar el plan del repositorio.

---

## 8. Acceso de emergencia

El PO tiene acceso de respaldo a la cuenta de Render del equipo. Las credenciales
están en el gestor de contraseñas compartido del equipo (ver en el canal privado
`#ops-credenciales`).
