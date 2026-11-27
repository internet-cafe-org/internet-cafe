# Producción en la nube (OPS-08)

Producción queda **montada sin desplegar** hasta la beta del martes 1/12 (HU-32, OPS-12).
Está separada de dev en los tres proveedores:

| Pieza | dev | prod |
|---|---|---|
| API (Render) | `internet-cafe-backend-dev` (`render.yaml`) | `internet-cafe-backend-prod` (`render.prod.yaml`) |
| Base (Neon) | proyecto `internet-cafe-dev` | proyecto `internet-cafe-prod` |
| Web (Vercel) | proyecto de dev (`frontend/vercel.json`) | segundo proyecto (`frontend/vercel.prod.json`) |
| GitHub | environment `dev`, sin aprobación | environment `prod`, con aprobación del PO o el SM |
| Despliegue | push a `main` (`deploy-dev`) | solo etiquetas `v*` (QA-17) |

Ningún secreto se versiona ni se imprime (SRS §13.3 y RNF-SEG-05). Las cuentas de Render,
Neon y Vercel las tiene Backend con el correo del proyecto; los secretos de GitHub los carga
el líder de Seguridad y Testing (HU-36). Este documento solo nombra los secretos.

## Orden

1. Roles de Neon prod.
2. Llaves de prod y su respaldo cifrado.
3. Servicio de Render prod.
4. Segundo proyecto de Vercel.
5. Environment `prod` de GitHub.
6. Verificación y evidencia en el issue #139.

## 1. Neon prod

El proyecto `internet-cafe-prod` ya existe (OPS-02). Falta crear sus roles:

1. Correr `Backend/db/bootstrap_roles.sql` contra `internet-cafe-prod` como `neondb_owner`,
   tal como explica `Backend/db/README.md`, con contraseñas nuevas, distintas de dev.
2. Guardar las contraseñas de `svc_migrator` y `svc_app` en el gestor de contraseñas del equipo.
3. Con ellas quedan dos URL:
   - `svc_app`: va en `DATABASE_URL` de Render prod.
   - `svc_migrator`: va en el secret `DATABASE_URL_MIGRATOR` del environment `prod` de GitHub.
     Nunca en Render (SRS §12.8).

## 2. Llaves de prod y respaldo cifrado fuera de línea

Las llaves de prod son **distintas** de las de dev. Se generan una sola vez, en un equipo de
confianza y fuera del repositorio:

```bash
cd Backend
python -m tools.generate_keys --out-dir <carpeta temporal fuera del repo>
```

El script crea:

| Archivo | Variable de Render prod |
|---|---|
| `jwt_es256_private.pem` | `JWT_PRIVATE_KEY` (pegar el PEM con saltos de línea reales) |
| `jwt_es256_public.pem` | `JWT_PUBLIC_KEY` |
| `data_enc_keys.json` | `DATA_ENC_KEYS` |
| `blind_index_key.txt` | `BLIND_INDEX_KEY` |

**Respaldo cifrado fuera de línea** (criterio de HU-32). Si se pierden `DATA_ENC_KEYS` o
`BLIND_INDEX_KEY`, los datos personales cifrados de prod no se pueden recuperar.

1. Comprimir la carpeta en un archivo cifrado con AES-256 y una frase de paso larga
   (por ejemplo, 7-Zip con "Encrypt file names" activado).
2. Guardar la frase de paso en el gestor de contraseñas del equipo, **separada** del archivo.
3. Dejar el archivo cifrado en dos ubicaciones fuera de línea y fuera de GitHub (por ejemplo,
   dos memorias USB que guardan dos personas distintas).
4. Borrar la carpeta temporal en claro.
5. Comentar en el issue #139 **quién** guarda cada copia y la fecha, sin rutas ni valores.

## 3. Render prod

1. En Render: **New → Blueprint**, este repositorio y, en **Blueprint Path**, `render.prod.yaml`.
2. Render pide los secretos (`sync: false`). Valores:
   - `DATABASE_URL`: URL de Neon prod con `svc_app`.
   - `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `DATA_ENC_KEYS` y `BLIND_INDEX_KEY`: las llaves del paso 2.
   - `ALLOWED_EMAIL_DOMAINS`: dominios institucionales (PEND-06), separados por coma.
   - `SECRET_KEY` la genera Render (`generateValue`).
3. Comprobar que el subdominio asignado sea `internet-cafe-backend-prod.onrender.com`. Si es otro,
   actualizar `PUBLIC_API_BASE_URL` en `render.prod.yaml` y el destino de `frontend/vercel.prod.json`.
4. Crear el deploy hook (Settings → Deploy Hook). Va en el secret `RENDER_DEPLOY_HOOK` del
   environment `prod` de GitHub, nunca en el repositorio.

**Montada sin desplegar.** Render construye el servicio al crear el Blueprint. Ese primer
despliegue solo sirve para verificar que arranca:

1. `GET https://internet-cafe-backend-prod.onrender.com/healthz` responde
   `{"status": "ok", "service": "backend"}`.
2. Después, **suspender** el servicio (Settings → Suspend Web Service) hasta la beta del 1/12.
   Así no consume horas del plan gratuito (SRS §13.4).
3. Las migraciones de prod no se corren a mano: las corre el pipeline de QA-17 con la primera
   etiqueta `v*`.

Valores fijos de prod en `render.prod.yaml`:

| Variable | Valor | Por qué |
|---|---|---|
| `APP_ENV` | `prod` | Desactiva los previews de Vercel en `/auth` |
| `RATE_LIMIT_ENABLED` | `true` | SRS §12.2 |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | MVP sin correo (backlog §4) |
| `plan` | `free`, 1 worker | SRS O-06 y §13.4: costo USD 0 |

## 4. Segundo proyecto de Vercel

1. Crear un proyecto nuevo de Vercel sobre este repositorio, con **Root Directory** `frontend/`
   y nombre `internet-cafe-prod`. El dominio esperado es `https://internet-cafe-prod.vercel.app`;
   si es otro, actualizar `FRONTEND_BASE_URL` en `render.prod.yaml`.
2. En **Settings → Git**, desconectar el repositorio. La web de prod solo se publica con la
   CLI de Vercel desde el pipeline de etiquetas (QA-17), con la configuración de prod:

   ```bash
   vercel deploy --prod --local-config vercel.prod.json
   ```

   `frontend/vercel.prod.json` es igual a `frontend/vercel.json`, salvo que `/api` apunta a
   Render prod. Si cambian las cabeceras de seguridad de `vercel.json`, hay que copiarlas aquí.
3. Generar un token de Vercel con alcance solo para este proyecto. Va en el environment `prod`
   de GitHub (paso 5).

## 5. Environment `prod` de GitHub

En **Settings → Environments → New environment** `prod`:

1. **Required reviewers:** el PO y el Scrum Master (backlog: "aprobación del PO o el SM para
   todo despliegue a producción").
2. **Deployment branches and tags:** solo etiquetas `v*`.
3. Secretos y variables, con los nombres y tipos que leen `deploy-prod.yml` (QA-17) y
   `release-msi.yml` (OPS-14):

| Nombre | Tipo | Valor | Lo usa |
|---|---|---|---|
| `DATABASE_URL_MIGRATOR` | secret | Neon prod con `svc_migrator` | `deploy-prod` |
| `RENDER_DEPLOY_HOOK` | secret | Deploy hook de Render prod | `deploy-prod` |
| `VERCEL_TOKEN` | secret | Token del proyecto de Vercel de prod | `deploy-prod` |
| `VERCEL_ORG_ID` | secret | Id del equipo u organización de Vercel | `deploy-prod` |
| `VERCEL_PROJECT_ID` | secret | Id del proyecto de Vercel de prod | `deploy-prod` |
| `PROD_API_URL` | variable | `https://internet-cafe-backend-prod.onrender.com` (sin `/` final) | `deploy-prod`, `release-msi` |
| `PROD_WEB_URL` | variable | `https://internet-cafe-prod.vercel.app` | `deploy-prod` |
| `PROD_ESPERA_DEPLOY_S` | variable (opcional) | Segundos de espera antes del humo; por defecto 420 | `deploy-prod` |

Los secretos de la semilla del piloto y del administrador inicial llegan con QA-18 y QA-02b.

## 6. Verificación

- [ ] Neon prod tiene `svc_migrator` y `svc_app`, con contraseñas distintas de dev.
- [ ] Las llaves de prod son distintas de las de dev, y el respaldo cifrado está en dos
      ubicaciones fuera de línea.
- [ ] Render prod responde `/healthz` y queda suspendido.
- [ ] Render prod tiene `APP_ENV=prod`.
- [ ] El segundo proyecto de Vercel existe, sin despliegues automáticos desde Git.
- [ ] El environment `prod` exige la aprobación del PO o el SM y solo acepta etiquetas `v*`.
- [ ] La evidencia está en el issue #139, sin valores secretos.
