# Contrato de Backend y Especificación de Datos / OpenAPI v0.2.1 - Sprint 2

> Fuente de verdad: el bloque YAML de este documento es idéntico a `openapi.yaml`.
> Estado: **borrador para aprobación** de los líderes de UI, Desktop y Seguridad.

## 1. Objetivo del Módulo
Contrato técnico y de datos de la API REST del sistema Internet Café, acordado con los equipos de UI, Desktop y Seguridad.

| Entrega | Contenido |
|---|---|
| **v0.2 · lunes 02/11** | Latido del equipo con `mode` y estado de sesión; sesión actual del equipo; cierres (`user_logout_pc`, `machine_shutdown`, y el aviso de cierres remotos por latido). |
| **v0.2 · martes 03/11** | `/me` (perfil, historial, sesión activa, cierre propio); administración (salas, equipos, sesiones y cierre forzado); firma por petición del equipo. |
| **v0.2.1 · sábado 14/11** | `/auth/*` y `/machine/enroll` según el SRS §10.3; autenticación de `/scan/*` y `/machine/challenges`; retiro de las rutas de v0.1 que nunca existieron en la API. |

## 2. Cambios

### v0.2.1 respecto a v0.2
- **Nuevo** `POST /auth/register` y `POST /auth/login` (SEC-02).
- **Documentados** `POST /auth/refresh` y `POST /auth/logout` (SEC-03a), que ya existían en la API pero no estaban en el YAML.
- **Nuevo** `POST /machine/enroll` (SEC-05), con la forma del SRS §8.4 y §12.4.
- **Documentados** `GET /healthz` y `GET /readyz`, fuera del prefijo `/api/v1`.
- **Cambia** `/scan/preview` y `/scan/claim`: exigen `bearerAuth`. El usuario sale del access token; se elimina la cabecera `X-User-Id`.
- **Cambia** `/machine/challenges` y `/machine/challenges/wait`: usan la misma autenticación que el resto de `/machine/*` (`machineSignature` o `machineProvisional`); ya no basta con `X-Machine-Code`.
- **Cambia** la cookie de refresh: se llama `__Secure-rt` (SRS §12.2); antes era `refresh_token`.
- **Nuevas** respuestas `Locked` (423), `TooManyRequests` (429) y `ServiceUnavailable` (503), y los esquemas `AccessToken`, `SessionUser`, `LoginResponse` y `MachineJwk`.
- **Retiradas** `/registro`, `/enroll`, `/credencial-provisional` y `/long-poll`: venían del borrador v0.1 y la API nunca las implementó. Sus reemplazos son `/auth/register`, `/machine/enroll`, la credencial que devuelve `/machine/enroll` y `/machine/challenges/wait`.

### v0.2 respecto a v0.1
- **Nuevo** `POST /machine/heartbeat`, `GET /machine/sessions/current`, `POST /machine/sessions/current/end`.
- **Nuevo** `GET /me`, `GET /me/sessions`, `GET /me/sessions/active`, `POST /me/sessions/{id}/end`.
- **Nuevo** `GET|POST /admin/labs`, `GET /admin/machines`, `PATCH /admin/machines/{id}`, `GET /admin/sessions`, `POST /admin/sessions/{id}/end`.
- **Nuevo** código de error genérico `CONFLICT` (409). Los demás vienen del catálogo del SRS §10.5.
- `ProblemDetails` pasa a llamarse `ProblemDetail` y es el único esquema de error (antes convivían los dos nombres); se añade `FieldError`.

### Impacto en los clientes
- **UI:** regenerar `frontend/src/api/schema.d.ts`; `services/auth.ts` ya usa la forma de `/auth/register` y `/auth/login`. La cookie cambia de nombre, pero la web no la lee (es HttpOnly).
- **Desktop:** `EnrollmentRequest` pasa a `{enrollment_code, jwk, proof, hostname?, app_version?}` y `EnrollmentResponse` a `{machine_id, code, lab, mode, keyid, provisional_credential}`, en `POST /machine/enroll`. `/machine/challenges` y `/machine/challenges/wait` deben enviar `X-Machine-Key` además de `X-Machine-Code`.

## 3. Autenticación por actor
| Esquema | Rutas | Detalle |
|---|---|---|
| Ninguno (público, con rate limit) | `/healthz`, `/readyz`, `/auth/register`, `/auth/login` | El rate limit llega con SEC-09 (`RATE_LIMIT_ENABLED`). |
| Cookie `__Secure-rt` + `Origin` | `/auth/refresh`, `/auth/logout` | Ver la sección 4. |
| `bearerAuth` | `/me/*`, `/scan/*`, `/admin/*` | Access token ES256 de 10 min (`alg` fijo, `iss`, `aud = web`, `sub`, `role`, `jti`). `/admin/*` exige `role = admin` (`FORBIDDEN` si no). |
| Código de un solo uso + prueba de posesión | `/machine/enroll` | Ver la sección 5. |
| `machineSignature` | `/machine/*` excepto enroll (objetivo) | RFC 9421 con `@method`, `@target-uri` y `content-digest` (RFC 9530). `created` ±30 s (`MACHINE_CLOCK_SKEW`); nonce no repetido en 60 s; firma ausente, inválida o repetida → `MACHINE_SIGNATURE_INVALID`. |
| `machineProvisional` | `/machine/*` excepto enroll (transitorio) | `X-Machine-Code` + `X-Machine-Key`. El servidor guarda solo el SHA-256 y compara en tiempo constante. Se retira con SEC-14, cuando la firma sea obligatoria (`MACHINE_AUTH_MODE=signature`). |

Los routers no cambian al activar la firma: solo se reemplaza la dependencia `require_machine`.

**Modo de autenticación del equipo (`MACHINE_AUTH_MODE`, SEC-07):**
- `token`: solo `X-Machine-Code` + `X-Machine-Key`.
- `dual` (dev hoy): si la petición trae `Signature-Input` y `Signature`, la firma debe ser válida; si no, se acepta la credencial provisional.
- `signature` (producción, y dev tras OPS-16): solo la firma.

**Salida transitoria (solo dev):** con `RETOS_ACEPTAN_SOLO_CODIGO=true`, `/machine/challenges` y `/machine/challenges/wait` aceptan una petición con solo `X-Machine-Code`, para no dejar sin QR al escritorio actual mientras se actualiza. Se ignora con `APP_ENV=prod`, cada uso queda en el log (`machine.retos_solo_codigo`) y se elimina con SEC-14.

Perfil de la firma (vectores en `contracts/test-vectors`, SEC-08): `sig1`, `ecdsa-p256-sha256`, componentes `@method`, `@target-uri` y, solo con cuerpo, `content-digest`; parámetros `created`, `keyid` (huella RFC 7638), `alg` y `nonce`; `@target-uri` = `PUBLIC_API_BASE_URL` + ruta + query; firma `r||s` de 64 bytes en base64.

## 4. Sesión web: registro, login, refresh y logout
- **Registro** (`POST /auth/register`): con datos válidos responde siempre 202 con el cuerpo vacío, también si el correo o el código estudiantil ya existen (no se crea otra cuenta ni se revela cuál existe). Contraseña de 10 a 128 caracteres (Argon2id); `privacy_consent` debe ser `true`; un dominio de correo no permitido devuelve 422. En el MVP la cuenta queda activa (`REQUIRE_EMAIL_VERIFICATION=false`, backlog §4) y la web inicia sesión sola.
- **Login** (`POST /auth/login`): devuelve `{access_token, token_type: "Bearer", expires_in, user: {id, full_name, role}}` y pone la cookie. Credenciales inválidas o cuenta bloqueada → 401 `AUTH_INVALID_CREDENTIALS`, sin distinguir si el correo existe.
- **Cookie:** `__Secure-rt`, HttpOnly, Secure, SameSite=Strict, `Path=/api/v1/auth`, 7 días. El refresh es opaco (256 bits), la API guarda solo su hash y nunca viaja en el cuerpo. El access token se entrega en el cuerpo y el cliente lo guarda en memoria.

| Método y ruta | Descripción | Respuestas |
|---|---|---|
| `POST /api/v1/auth/refresh` | Rota el refresh (revoca el usado y emite otro en la misma familia) y devuelve `{access_token, token_type, expires_in}` | 200; 401 `AUTH_INVALID_CREDENTIALS` (sin cookie, desconocido, revocado o reutilizado); 401 `AUTH_TOKEN_EXPIRED` (vencido); 403 `FORBIDDEN` (`Origin` no permitido) |
| `POST /api/v1/auth/logout` | Revoca la familia del token y borra la cookie. Idempotente | 204; 403 `FORBIDDEN` (`Origin` no permitido) |

Si se presenta un refresh token ya revocado **fuera de la gracia de 10 s** se considera robo y se revoca toda la familia. Dentro de la gracia (dos pestañas que renuevan a la vez) se emite otro token de la misma familia (SEC-03b). `Origin` se valida contra `FRONTEND_BASE_URL`, `ALLOWED_ORIGIN` y, solo en dev, `ORIGEN_PREVIEW_REGEX`.

**Bloqueo y límites (SEC-09):** 5 contraseñas fallidas seguidas bloquean la cuenta 15 min (423 `AUTH_ACCOUNT_LOCKED`). `/auth/*`, `/scan/claim` y `/machine/enroll` admiten 10 peticiones por minuto por cuenta y por IP (429 `RATE_LIMITED` con `Retry-After`); el refresh solo cuenta por su token.

## 5. Enrolamiento del equipo (`POST /machine/enroll`)
1. El administrador genera un código de un solo uso que vence en 24 h. En el MVP lo genera la semilla de dev (QA-02a); el endpoint de administración llega con BE-13.
2. El equipo genera un par ECDSA P-256 y envía `{enrollment_code, jwk, proof}`. `jwk` es la clave pública (`kty = EC`, `crv = P-256`, `x`, `y`; sin `d`). `proof` es la firma ECDSA P-256 / SHA-256 de los bytes UTF-8 de `enrollment_code`, en formato `r||s` de 64 bytes y base64url sin relleno.
3. La API valida el JWK, verifica la firma, calcula la huella RFC 7638 (`keyid`), marca el código como usado, pasa el equipo a `active`, emite la credencial provisional y audita `machine.enroll`. Todo en una transacción.
4. Respuesta 201: `{machine_id, code, lab, mode, keyid, provisional_credential}`. La credencial se muestra una sola vez; la API guarda solo su hash.

Errores: código inexistente, usado o vencido → 401 `ENROLLMENT_CODE_INVALID`; firma inválida → 401 `MACHINE_SIGNATURE_INVALID`; JWK inválido → 422 `VALIDATION_ERROR`; clave ya registrada por otro equipo → 409 `CONFLICT`.

## 6. Latido y cierres
- `POST /machine/heartbeat` (cada 60 s): `{ "server_time", "mode", "session_status", "session_id?", "end_reason?" }`.
  `session_status`: `active` | `ended` | `none`. El equipo envía `session_id` con la sesión que cree tener; si ya cerró, recibe `ended` y el `end_reason`, que es como se entera de un cierre remoto (web, administrador o reemplazo).
- Motivos de cierre (`end_reason`): `user_logout_pc`, `user_logout_web`, `superseded`, `heartbeat_timeout`, `admin_forced`, `machine_shutdown`.
- Un cierre es atómico e idempotente: el primero gana y un reintento devuelve el estado final sin error.
- Sin latido durante 3 min la API cierra la sesión con `ended_at = last_heartbeat_at` (RN-07; tarea periódica).

## 7. Formato de errores (QA-03)
- Todos los errores salen como `application/problem+json` con el esquema `ProblemDetail`.
- `type` se arma con `ERRORS_BASE_URL` más el `code` en kebab-case (`CHALLENGE_EXPIRED` → `/challenge-expired`).
- Los 422 llevan `code: VALIDATION_ERROR` y `errors[]` con `field` y `message`. No devuelven `input` ni `ctx`, para no repetir contraseñas u otros datos del cliente. Los cuerpos de `/auth/*`, `/machine/enroll`, `/machine/heartbeat`, `/me` y `/admin` rechazan campos desconocidos.
- Además del catálogo del SRS §10.5 existen los códigos genéricos `BAD_REQUEST`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `INTERNAL_ERROR` y `CONFLICT`.
- Un 500 no incluye la traza; el servidor registra un `request_id` que viaja en la cabecera `X-Request-ID`.
- Ninguna respuesta incluye contraseñas, hashes, refresh tokens, claves privadas ni el código de estudiante completo (siempre `student_code_masked`). La única excepción es `provisional_credential`, que `/machine/enroll` entrega una sola vez.

## 8. Especificación OpenAPI v0.2.1
```yaml
openapi: 3.0.3
info:
  title: Internet Cafe API - Contrato
  version: 0.2.1
  description: 'Contrato de datos y endpoints. v0.2.1: agrega /auth/* (registro, login, refresh y logout), /machine/enroll,
    /healthz y /readyz; /scan/* exige el access token y /machine/challenges usa la autenticación del equipo; se
    retiran las rutas de v0.1 que nunca existieron en la API (/registro, /enroll, /credencial-provisional y /long-poll).
    v0.2 (BE-18): latido con `mode`, sesión actual y cierres del equipo; /me; administración; firma por petición
    del equipo.'
paths:
  /healthz:
    get:
      tags:
      - salud
      security: []
      summary: Liveness
      description: Responde sin tocar la base de datos. Fuera del prefijo `/api/v1`.
      responses:
        '200':
          description: La API está viva.
          content:
            application/json:
              schema:
                type: object
                required:
                - status
                properties:
                  status:
                    type: string
                    example: ok
  /readyz:
    get:
      tags:
      - salud
      security: []
      summary: Readiness
      description: Verifica la conexión a la base de datos. Fuera del prefijo `/api/v1`.
      responses:
        '200':
          description: La base de datos responde.
          content:
            application/json:
              schema:
                type: object
                required:
                - status
                properties:
                  status:
                    type: string
                    example: ready
        '503':
          $ref: '#/components/responses/ServiceUnavailable'
  /api/v1/auth/register:
    post:
      tags:
      - auth
      security: []
      summary: Registro de estudiante (SEC-02)
      description: Crea la cuenta con los datos personales cifrados (interfaz `pii`) y la contraseña en Argon2id.
        Con datos válidos responde **siempre 202**, también si el correo o el código ya existen; en ese caso no
        crea otra cuenta ni revela cuál existe (RF-AUT-01). En el MVP la cuenta queda activa (`REQUIRE_EMAIL_VERIFICATION=false`,
        backlog §4) y la web inicia sesión sola con `/auth/login`.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties: false
              required:
              - email
              - student_code
              - full_name
              - password
              - privacy_consent
              properties:
                email:
                  type: string
                  format: email
                  maxLength: 254
                  description: Correo institucional. Un dominio no permitido (`ALLOWED_EMAIL_DOMAINS`) devuelve
                    422.
                  example: ana.perez@universidad.edu.co
                student_code:
                  type: string
                  minLength: 4
                  maxLength: 20
                  pattern: ^[0-9A-Za-z-]+$
                  example: '2021123434'
                full_name:
                  type: string
                  minLength: 2
                  maxLength: 120
                  example: Ana Pérez
                password:
                  type: string
                  format: password
                  minLength: 10
                  maxLength: 128
                privacy_consent:
                  type: boolean
                  enum:
                  - true
                  description: Aceptación explícita del tratamiento de datos.
      responses:
        '202':
          description: Solicitud aceptada. Cuerpo vacío; no revela si la cuenta ya existía.
        '422':
          $ref: '#/components/responses/ValidationError'
        '429':
          $ref: '#/components/responses/TooManyRequests'
  /api/v1/auth/login:
    post:
      tags:
      - auth
      security: []
      summary: Inicio de sesión (SEC-02)
      description: Emite el access token ES256 (10 min, `aud = web`) y pone la cookie de refresh `__Secure-rt`.
        Credenciales inválidas → 401 `AUTH_INVALID_CREDENTIALS` sin distinguir si el correo existe; cuenta bloqueada
        por el administrador → 401 `AUTH_INVALID_CREDENTIALS`; cuenta sin verificar (solo con `REQUIRE_EMAIL_VERIFICATION=true`)
        → 403 `AUTH_EMAIL_NOT_VERIFIED`.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties: false
              required:
              - email
              - password
              properties:
                email:
                  type: string
                  format: email
                  maxLength: 254
                password:
                  type: string
                  format: password
                  minLength: 1
                  maxLength: 128
      responses:
        '200':
          description: Sesión iniciada.
          headers:
            Set-Cookie:
              description: '`__Secure-rt=<refresh opaco>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth;
                Max-Age=604800`. El refresh nunca viaja en el cuerpo.'
              schema:
                type: string
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LoginResponse'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '422':
          $ref: '#/components/responses/ValidationError'
        '423':
          $ref: '#/components/responses/Locked'
        '429':
          $ref: '#/components/responses/TooManyRequests'
  /api/v1/auth/refresh:
    post:
      tags:
      - auth
      security: []
      summary: Renovar el access token (SEC-03a)
      description: 'Rota el refresh de la cookie (revoca el usado y emite otro en la misma familia) y devuelve un
        access token nuevo. Sin cookie, desconocido, revocado o reutilizado → 401 `AUTH_INVALID_CREDENTIALS`; vencido
        → 401 `AUTH_TOKEN_EXPIRED`. Presentar un refresh ya revocado revoca toda la familia. Responde con `Cache-Control:
        no-store`.'
      parameters:
      - in: cookie
        name: __Secure-rt
        required: false
        description: Refresh token opaco de 256 bits; la API solo guarda su hash.
        schema:
          type: string
      - in: header
        name: Origin
        required: false
        description: Si viene, debe ser el origen permitido (`ALLOWED_ORIGIN`); si no, 403 `FORBIDDEN`.
        schema:
          type: string
      responses:
        '200':
          description: Access token renovado.
          headers:
            Set-Cookie:
              description: '`__Secure-rt=<refresh opaco>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth;
                Max-Age=604800`. El refresh nunca viaja en el cuerpo.'
              schema:
                type: string
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AccessToken'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/auth/logout:
    post:
      tags:
      - auth
      security: []
      summary: Cerrar la sesión web (SEC-03a)
      description: 'Revoca la familia del refresh de la cookie y la borra. Idempotente: responde 204 aunque no haya
        cookie.'
      parameters:
      - in: cookie
        name: __Secure-rt
        required: false
        description: Refresh token opaco de 256 bits; la API solo guarda su hash.
        schema:
          type: string
      - in: header
        name: Origin
        required: false
        description: Si viene, debe ser el origen permitido (`ALLOWED_ORIGIN`); si no, 403 `FORBIDDEN`.
        schema:
          type: string
      responses:
        '204':
          description: Sesión cerrada.
          headers:
            Set-Cookie:
              description: Borra la cookie `__Secure-rt` (`Max-Age=0`).
              schema:
                type: string
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/machine/enroll:
    post:
      tags:
      - machine
      security: []
      summary: Enrolar el equipo con su clave pública (SEC-05)
      description: 'El equipo envía el código de un solo uso, su clave pública P-256 en JWK y una prueba de posesión:
        la firma ECDSA P-256 / SHA-256 de los bytes UTF-8 de `enrollment_code`, en formato `r||s` de 64 bytes y
        base64url sin relleno. La API valida el JWK (P-256, sin `d`), verifica la firma, calcula la huella RFC 7638
        (`keyid`), marca el código como usado, pasa el equipo a `active`, emite la credencial provisional (se muestra
        una sola vez; la API guarda solo su hash) y audita `machine.enroll`. Código inexistente, usado o vencido
        → 401 `ENROLLMENT_CODE_INVALID`; firma inválida → 401 `MACHINE_SIGNATURE_INVALID`; JWK inválido → 422; clave
        ya usada por otro equipo → 409 `CONFLICT`.'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties: false
              required:
              - enrollment_code
              - jwk
              - proof
              properties:
                enrollment_code:
                  type: string
                  minLength: 8
                  maxLength: 64
                  description: Código de un solo uso; vence en 24 h.
                jwk:
                  $ref: '#/components/schemas/MachineJwk'
                proof:
                  type: string
                  description: Firma `r||s` (64 bytes) en base64url sin relleno.
                  example: MEUCIQ…
                hostname:
                  type: string
                  maxLength: 63
                  nullable: true
                app_version:
                  type: string
                  maxLength: 20
                  nullable: true
      responses:
        '201':
          description: Equipo enrolado.
          content:
            application/json:
              schema:
                type: object
                required:
                - machine_id
                - code
                - lab
                - mode
                - keyid
                - provisional_credential
                properties:
                  machine_id:
                    type: string
                    format: uuid
                  code:
                    type: string
                    example: LAB3-PC12
                  lab:
                    type: string
                    nullable: true
                    example: Sala 3 · Bloque B
                  mode:
                    $ref: '#/components/schemas/MachineMode'
                  keyid:
                    type: string
                    description: Huella RFC 7638 del JWK (base64url de SHA-256).
                    example: NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs
                  provisional_credential:
                    type: string
                    description: TRANSITORIO. Valor de `X-Machine-Key`. Se muestra una sola vez y se retira con
                      SEC-14, cuando la firma RFC 9421 sea obligatoria.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          $ref: '#/components/responses/ValidationError'
        '429':
          $ref: '#/components/responses/TooManyRequests'
  /api/v1/machine/challenges:
    post:
      tags:
      - machine
      security:
      - machineSignature: []
      - machineProvisional: []
      summary: Generar un reto QR para una máquina
      description: Crea un reto QR de un solo uso para el equipo identificado. Máximo 2 retos vigentes por equipo
        (RN-06).
      responses:
        '201':
          description: Reto QR creado correctamente.
          content:
            application/json:
              schema:
                type: object
                required:
                - challenge_id
                - qr_url
                - expires_at
                - rotate_after_s
                properties:
                  challenge_id: &id001
                    type: string
                    format: uuid
                  qr_url:
                    type: string
                    format: uri
                  expires_at: &id002
                    type: string
                    format: date-time
                  rotate_after_s:
                    type: integer
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/machine/challenges/wait:
    get:
      tags:
      - machine
      security:
      - machineSignature: []
      - machineProvisional: []
      summary: Espera en long-poll de la aprobación de un reto QR
      description: Mantiene la conexión abierta hasta que un estudiante reclame el reto QR del equipo o venza el
        timeout.
      parameters:
      - in: query
        name: timeout
        required: false
        schema:
          type: integer
          minimum: 1
          maximum: 25
          default: 25
      responses:
        '200':
          description: Respuesta de long-poll (sesión aprobada o en espera).
          content:
            application/json:
              schema:
                type: object
                required:
                - status
                properties:
                  status:
                    type: string
                    enum:
                    - approved
                    - waiting
                  session:
                    type: object
                    required:
                    - id
                    - status
                    - started_at
                    properties:
                      id: *id001
                      status:
                        type: string
                        example: active
                      started_at: *id002
                  user:
                    $ref: '#/components/schemas/StudentInfo'
                  recent_accesses:
                    type: array
                    items:
                      $ref: '#/components/schemas/RecentAccess'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/scan/preview:
    post:
      tags:
      - scan
      security:
      - bearerAuth: []
      summary: Consultar vista previa de un reto QR
      description: Obtiene información del equipo antes de confirmar el acceso. No consume el reto. Exige el access
        token del estudiante; el usuario sale del token, nunca de una cabecera.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
              - token
              properties:
                token:
                  type: string
      responses:
        '200':
          description: Vista previa obtenida correctamente.
          content:
            application/json:
              schema:
                type: object
                required:
                - machine
                - expires_at
                - active_session
                properties:
                  machine:
                    type: object
                    required:
                    - code
                    - lab
                    properties:
                      code:
                        type: string
                      lab:
                        type: string
                  expires_at: *id002
                  active_session:
                    type: object
                    nullable: true
                    properties:
                      machine_code:
                        type: string
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '410':
          $ref: '#/components/responses/Gone'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/scan/claim:
    post:
      tags:
      - scan
      security:
      - bearerAuth: []
      summary: Confirmar acceso escaneando el QR (Claim)
      description: Reclama el reto QR y crea la sesión de acceso para el estudiante de forma atómica. Exige el access
        token del estudiante; el usuario sale del token, nunca de una cabecera.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
              - token
              properties:
                token:
                  type: string
      responses:
        '201':
          description: Sesión creada exitosamente.
          content:
            application/json:
              schema: &id003
                type: object
                required:
                - session
                properties:
                  session:
                    type: object
                    required:
                    - id
                    - status
                    - started_at
                    - machine
                    properties:
                      id: *id001
                      status:
                        type: string
                        example: active
                      started_at: *id002
                      machine:
                        type: object
                        required:
                        - id
                        - code
                        - lab
                        properties:
                          id: *id001
                          code:
                            type: string
                          lab:
                            type: string
        '200':
          description: Reintento idempotente exitoso (devuelve la sesión existente).
          content:
            application/json:
              schema: *id003
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '410':
          $ref: '#/components/responses/Gone'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '422':
          $ref: '#/components/responses/ValidationError'
        '429':
          $ref: '#/components/responses/TooManyRequests'
  /api/v1/machine/heartbeat:
    post:
      tags:
      - machine
      security: &id004
      - machineSignature: []
      - machineProvisional: []
      summary: Latido del equipo (v0.2)
      description: 'El equipo lo envía cada 60 s. Devuelve la hora del servidor, el modo del equipo (`mode`) y el
        estado de su sesión. Es la vía por la que el equipo se entera de un cierre remoto (web, administrador o
        reemplazo): si no tiene sesión abierta y envía `session_id`, responde `ended` con `end_reason`. Solo equipos
        `active` pueden enviar latidos (RN-08). Toda marca de tiempo la fija el servidor (RN-01).'
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/HeartbeatRequest'
      responses:
        '200':
          description: Latido registrado.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HeartbeatResponse'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/machine/sessions/current:
    get:
      tags:
      - machine
      security: *id004
      summary: Sesión actual del equipo (v0.2)
      description: Sesión abierta del equipo con el estudiante enmascarado y sus últimos accesos. 204 si el equipo
        no tiene sesión abierta.
      responses:
        '200':
          description: Sesión abierta.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CurrentSession'
        '204':
          description: El equipo no tiene sesión abierta.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/machine/sessions/current/end:
    post:
      tags:
      - machine
      security: *id004
      summary: Cerrar la sesión desde el equipo (v0.2)
      description: Cierra la sesión abierta del equipo con motivo `user_logout_pc` (por defecto) o `machine_shutdown`
        (apagado ordenado, mejor esfuerzo).
      requestBody:
        required: false
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/EndSessionRequest'
      responses:
        '200':
          description: Sesión cerrada.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EndedSession'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/me:
    get:
      tags:
      - me
      security: &id005
      - bearerAuth: []
      summary: Perfil del usuario (v0.2)
      description: Perfil del usuario autenticado. El código de estudiante se devuelve enmascarado.
      responses:
        '200':
          description: Perfil.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Profile'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
  /api/v1/me/password:
    patch:
      tags:
      - me
      security:
      - bearerAuth: []
      summary: Cambiar la contraseña propia (SEC-02)
      description: >-
        Cambia la contraseña del usuario autenticado. Exige la contraseña actual.
        La nueva debe tener entre 10 y 128 caracteres y ser distinta de la actual.
        Al cambiarla se cierran las demás sesiones web (refresh tokens); la sesión
        que hizo el cambio sigue abierta. Una contraseña actual incorrecta responde
        422 `VALIDATION_ERROR` (no 401, para que el cliente no lo confunda con un
        token vencido). Límite por cuenta, 429 `RATE_LIMITED`.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              additionalProperties: false
              required:
              - current_password
              - new_password
              properties:
                current_password:
                  type: string
                  format: password
                  minLength: 1
                  maxLength: 128
                new_password:
                  type: string
                  format: password
                  minLength: 10
                  maxLength: 128
      responses:
        '204':
          description: Contraseña cambiada. Sin cuerpo.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '422':
          $ref: '#/components/responses/ValidationError'
        '429':
          description: Demasiados intentos. Espera lo indicado en `Retry-After`.
  /api/v1/me/sessions:
    get:
      tags:
      - me
      security: *id005
      summary: Historial de sesiones propias (v0.2)
      description: Historial paginado, de la más reciente a la más antigua.
      parameters:
      - &id006
        in: query
        name: limit
        schema:
          type: integer
          minimum: 1
          maximum: 100
          default: 20
      - &id007
        in: query
        name: offset
        schema:
          type: integer
          minimum: 0
          default: 0
      responses:
        '200':
          description: Página de sesiones.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MySessionsPage'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/me/sessions/active:
    get:
      tags:
      - me
      security: *id005
      summary: Sesión activa propia (v0.2)
      description: 'Sesión abierta del usuario o `{"session": null}`.'
      responses:
        '200':
          description: Sesión activa o null.
          content:
            application/json:
              schema:
                type: object
                required:
                - session
                properties:
                  session:
                    $ref: '#/components/schemas/MySession'
                    nullable: true
        '401':
          $ref: '#/components/responses/Unauthorized'
  /api/v1/me/sessions/{id}/end:
    post:
      tags:
      - me
      security: *id005
      summary: Cerrar una sesión propia desde la web (v0.2)
      description: Cierra con motivo `user_logout_web`. Idempotente. El equipo se entera en su próximo latido (≤
        60 s). Una sesión ajena responde igual que una inexistente (404 `SESSION_NOT_FOUND`).
      parameters:
      - in: path
        name: id
        required: true
        schema: *id001
      responses:
        '200':
          description: Sesión (cerrada).
          content:
            application/json:
              schema:
                type: object
                required:
                - session
                properties:
                  session:
                    $ref: '#/components/schemas/MySession'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/labs:
    get:
      tags:
      - admin
      security: *id005
      summary: Listar salas (v0.2)
      parameters:
      - *id006
      - *id007
      responses:
        '200':
          description: Página de salas.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LabsPage'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
    post:
      tags:
      - admin
      security: *id005
      summary: Crear una sala (v0.2)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/LabCreate'
      responses:
        '201':
          description: Sala creada.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Lab'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/labs/{id}:
    patch:
      tags:
      - admin
      security: *id005
      summary: Editar nombre o edificio de una sala (BE-12)
      parameters:
      - in: path
        name: id
        required: true
        schema: *id001
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/LabPatch'
      responses:
        '200':
          description: Sala actualizada.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Lab'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/machines:
    post:
      tags:
      - admin
      security: *id005
      summary: Crear un equipo (BE-12)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MachineCreate'
      responses:
        '201':
          description: Equipo creado en estado pending_enrollment.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Machine'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          $ref: '#/components/responses/ValidationError'
    get:
      tags:
      - admin
      security: *id005
      summary: Listar equipos (v0.2)
      parameters:
      - in: query
        name: lab_id
        schema: *id001
      - in: query
        name: status
        schema:
          $ref: '#/components/schemas/MachineStatus'
      - *id006
      - *id007
      responses:
        '200':
          description: Página de equipos.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MachinesPage'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/machines/{id}:
    patch:
      tags:
      - admin
      security: *id005
      summary: Editar sala, modo o estado de un equipo (v0.2)
      description: 'Deshabilitar un equipo (`status: disabled`) cancela sus retos pendientes y cierra su sesión
        abierta con `admin_forced` (RN-08). Activar un equipo que no se enroló responde 409 `CONFLICT`.'
      parameters:
      - in: path
        name: id
        required: true
        schema: *id001
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/MachinePatch'
      responses:
        '200':
          description: Equipo actualizado.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Machine'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/sessions:
    get:
      tags:
      - admin
      security: *id005
      summary: Consultar accesos con filtros (v0.2)
      parameters:
      - in: query
        name: machine_code
        schema:
          type: string
          maxLength: 40
      - in: query
        name: lab_id
        schema: *id001
      - in: query
        name: state
        schema:
          type: string
          enum:
          - active
          - ended
      - in: query
        name: started_from
        schema: *id002
        description: Inclusivo. Sin zona horaria se interpreta como UTC.
      - in: query
        name: started_to
        schema: *id002
        description: Exclusivo. Sin zona horaria se interpreta como UTC.
      - *id006
      - *id007
      responses:
        '200':
          description: Página de sesiones.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AdminSessionsPage'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '422':
          $ref: '#/components/responses/ValidationError'
  /api/v1/admin/sessions/{id}/end:
    post:
      tags:
      - admin
      security: *id005
      summary: Cierre forzado de una sesión (v0.2)
      description: Cierra con motivo `admin_forced`. Idempotente. El equipo se entera en su próximo latido (≤ 60
        s).
      parameters:
      - in: path
        name: id
        required: true
        schema: *id001
      responses:
        '200':
          description: Sesión (cerrada).
          content:
            application/json:
              schema:
                type: object
                required:
                - session
                properties:
                  session:
                    $ref: '#/components/schemas/AdminSession'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '422':
          $ref: '#/components/responses/ValidationError'
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
      description: Access token ES256 de 10 min (SEC-00). Rutas /me y /admin; /admin exige además `role = admin`.
    machineProvisional:
      type: apiKey
      in: header
      name: X-Machine-Key
      description: TRANSITORIO. Credencial provisional del equipo, enviada junto con `X-Machine-Code`; el servidor
        solo guarda su SHA-256 y la compara en tiempo constante. Se retira cuando Seguridad active la firma.
    machineSignature:
      type: apiKey
      in: header
      name: Signature
      description: 'OBJETIVO v0.2 (RFC 9421 + RFC 9530). Cabeceras: `Content-Digest: sha-256=:<base64>:`, `Signature-Input:
        sig1=("@method" "@target-uri" "content-digest");created=<epoch>;nonce="<id>";keyid="<thumbprint>";alg="ecdsa-p256-sha256"`
        y `Signature: sig1=:<r||s 64 bytes base64>:`. Tolerancia de reloj ±30 s (`MACHINE_CLOCK_SKEW`), nonce no
        repetido en 60 s, firma inválida o repetida → `MACHINE_SIGNATURE_INVALID`. Estado: contrato propuesto; la
        verificación en el servidor la entrega el equipo de Seguridad.'
  schemas:
    ProblemDetail:
      type: object
      description: Error RFC 9457. Toda respuesta 4xx/5xx usa este esquema con `application/problem+json`. Nunca
        incluye credenciales, tokens, el valor enviado (`input`) ni trazas.
      required:
      - type
      - title
      - status
      - code
      - detail
      - instance
      properties:
        type:
          type: string
          format: uri
          example: https://errors.internet-cafe.example/challenge-expired
        title:
          type: string
          example: El código QR expiró
        status:
          type: integer
          example: 410
        code:
          type: string
          description: Código estable del catálogo (SRS §10.5).
          example: CHALLENGE_EXPIRED
        detail:
          type: string
          example: Escanea el código nuevo del equipo.
        instance:
          type: string
          description: Ruta de la petición, sin query string.
          example: /api/v1/scan/claim
        errors:
          type: array
          description: Solo en 422.
          items:
            $ref: '#/components/schemas/FieldError'
    FieldError:
      type: object
      required:
      - field
      - message
      properties:
        field:
          type: string
          example: body.password
        message:
          type: string
          example: String should have at least 12 characters
    StudentInfo:
      type: object
      required:
      - full_name
      - student_code_masked
      properties:
        full_name:
          type: string
          example: Ana Pérez
        student_code_masked:
          type: string
          example: 2021****34
    RecentAccess:
      type: object
      required:
      - machine_code
      - lab
      - started_at
      - ended_at
      - duration_s
      properties:
        machine_code:
          type: string
        lab:
          type: string
        started_at: *id002
        ended_at: *id002
        duration_s:
          type: integer
    SessionEndReason:
      type: string
      enum:
      - user_logout_pc
      - user_logout_web
      - superseded
      - heartbeat_timeout
      - admin_forced
      - machine_shutdown
    MachineStatus:
      type: string
      enum:
      - pending_enrollment
      - active
      - disabled
    MachineMode:
      type: string
      enum:
      - passive
      - kiosk
    HeartbeatRequest:
      type: object
      additionalProperties: false
      properties:
        session_id:
          type: string
          format: uuid
          nullable: true
          description: Sesión que el equipo cree tener abierta. Permite informarle un cierre remoto.
    HeartbeatResponse:
      type: object
      required:
      - server_time
      - mode
      - session_status
      properties:
        server_time: *id002
        mode:
          $ref: '#/components/schemas/MachineMode'
        session_status:
          type: string
          enum:
          - active
          - ended
          - none
          description: '`active`: hay sesión abierta. `ended`: la sesión indicada en la petición ya cerró (ver `end_reason`).
            `none`: no hay sesión.'
        session_id:
          type: string
          format: uuid
          description: Sesión abierta actual (`active`) o la indicada en la petición (`ended`). Si difiere de la
            que el equipo tiene, debe resincronizar con GET /machine/sessions/current.
        end_reason:
          $ref: '#/components/schemas/SessionEndReason'
    CurrentSession:
      type: object
      required:
      - session
      - user
      - recent_accesses
      properties:
        session:
          type: object
          required:
          - id
          - status
          - started_at
          properties:
            id: *id001
            status:
              type: string
              enum:
              - active
            started_at: *id002
        user:
          $ref: '#/components/schemas/StudentInfo'
        recent_accesses:
          type: array
          items:
            $ref: '#/components/schemas/RecentAccess'
    EndSessionRequest:
      type: object
      additionalProperties: false
      properties:
        reason:
          type: string
          enum:
          - user_logout_pc
          - machine_shutdown
          default: user_logout_pc
    EndedSession:
      type: object
      required:
      - session
      properties:
        session:
          type: object
          required:
          - id
          - status
          - ended_at
          - end_reason
          properties:
            id: *id001
            status:
              type: string
              enum:
              - closed
            ended_at: *id002
            end_reason:
              $ref: '#/components/schemas/SessionEndReason'
    Profile:
      type: object
      required:
      - id
      - full_name
      - email
      - student_code_masked
      - role
      - status
      properties:
        id: *id001
        full_name:
          type: string
        email:
          type: string
          format: email
        student_code_masked:
          type: string
        role:
          type: string
          enum:
          - student
          - admin
        status:
          type: string
          enum:
          - pending_verification
          - active
          - blocked
    MySession:
      type: object
      required:
      - id
      - machine_code
      - lab
      - started_at
      properties:
        id: *id001
        machine_code:
          type: string
        lab:
          type: string
        started_at: *id002
        ended_at:
          type: string
          format: date-time
          nullable: true
        end_reason:
          $ref: '#/components/schemas/SessionEndReason'
          nullable: true
        duration_s:
          type: integer
          nullable: true
    MySessionsPage:
      type: object
      required:
      - items
      - total
      - limit
      - offset
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/MySession'
        total:
          type: integer
        limit:
          type: integer
        offset:
          type: integer
    LabCreate:
      type: object
      additionalProperties: false
      required:
      - name
      properties:
        name:
          type: string
          minLength: 1
          maxLength: 80
        building:
          type: string
          maxLength: 80
          nullable: true
    LabPatch:
      type: object
      additionalProperties: false
      minProperties: 1
      properties:
        name:
          type: string
          minLength: 1
          maxLength: 80
        building:
          type: string
          maxLength: 80
          nullable: true
    Lab:
      type: object
      required:
      - id
      - name
      properties:
        id: *id001
        name:
          type: string
        building:
          type: string
          nullable: true
    LabsPage:
      type: object
      required:
      - items
      - total
      - limit
      - offset
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/Lab'
        total:
          type: integer
        limit:
          type: integer
        offset:
          type: integer
    MachineCreate:
      type: object
      additionalProperties: false
      required:
      - code
      properties:
        code:
          type: string
          minLength: 1
          maxLength: 40
        lab_id:
          type: string
          format: uuid
          nullable: true
        mode:
          $ref: '#/components/schemas/MachineMode'
    MachinePatch:
      type: object
      additionalProperties: false
      minProperties: 1
      properties:
        lab_id:
          type: string
          format: uuid
          nullable: true
          description: null desasigna la sala.
        mode:
          $ref: '#/components/schemas/MachineMode'
        status:
          type: string
          enum:
          - active
          - disabled
    Machine:
      type: object
      required:
      - id
      - code
      - status
      - mode
      properties:
        id: *id001
        code:
          type: string
        hostname:
          type: string
          nullable: true
        lab_id:
          type: string
          format: uuid
          nullable: true
        lab:
          type: string
          nullable: true
        status:
          $ref: '#/components/schemas/MachineStatus'
        mode:
          $ref: '#/components/schemas/MachineMode'
        app_version:
          type: string
          nullable: true
        enrolled_at:
          type: string
          format: date-time
          nullable: true
        last_seen_at:
          type: string
          format: date-time
          nullable: true
    MachinesPage:
      type: object
      required:
      - items
      - total
      - limit
      - offset
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/Machine'
        total:
          type: integer
        limit:
          type: integer
        offset:
          type: integer
    AdminSession:
      type: object
      required:
      - id
      - user
      - machine_code
      - lab
      - started_at
      - last_heartbeat_at
      properties:
        id: *id001
        user:
          type: object
          required:
          - id
          - full_name
          - student_code_masked
          properties:
            id: *id001
            full_name:
              type: string
            student_code_masked:
              type: string
        machine_code:
          type: string
        lab:
          type: string
        started_at: *id002
        last_heartbeat_at: *id002
        ended_at:
          type: string
          format: date-time
          nullable: true
        end_reason:
          $ref: '#/components/schemas/SessionEndReason'
          nullable: true
        duration_s:
          type: integer
          nullable: true
    AdminSessionsPage:
      type: object
      required:
      - items
      - total
      - limit
      - offset
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/AdminSession'
        total:
          type: integer
        limit:
          type: integer
        offset:
          type: integer
    AccessToken:
      type: object
      description: Access token ES256 de 10 min. El cliente lo guarda en memoria; el refresh viaja solo en la cookie
        `__Secure-rt`.
      required:
      - access_token
      - token_type
      - expires_in
      properties:
        access_token:
          type: string
          example: eyJhbGciOiJFUzI1NiJ9…
        token_type:
          type: string
          enum:
          - Bearer
        expires_in:
          type: integer
          description: Segundos de vida del access token.
          example: 600
    SessionUser:
      type: object
      required:
      - id
      - full_name
      - role
      properties:
        id:
          type: string
          format: uuid
        full_name:
          type: string
          example: Ana Pérez
        role:
          type: string
          enum:
          - student
          - admin
    LoginResponse:
      allOf:
      - $ref: '#/components/schemas/AccessToken'
      - type: object
        required:
        - user
        properties:
          user:
            $ref: '#/components/schemas/SessionUser'
    MachineJwk:
      type: object
      description: Clave pública EC P-256 (RFC 7517). No puede incluir la parte privada (`d`).
      required:
      - kty
      - crv
      - x
      - y
      additionalProperties: false
      properties:
        kty:
          type: string
          enum:
          - EC
        crv:
          type: string
          enum:
          - P-256
        x:
          type: string
          description: Coordenada x en base64url sin relleno (32 bytes).
          example: f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU
        y:
          type: string
          description: Coordenada y en base64url sin relleno (32 bytes).
          example: x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0
  responses:
    BadRequest:
      description: Petición inválida.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    Unauthorized:
      description: 'No autorizado: token ausente o vencido, o firma/credencial del equipo inválida.'
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    Forbidden:
      description: 'Acceso prohibido: sin permisos, o equipo deshabilitado.'
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    NotFound:
      description: Recurso no encontrado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    Conflict:
      description: Conflicto con el estado actual del recurso.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    Gone:
      description: Reto QR expirado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    ValidationError:
      description: 422 `VALIDATION_ERROR` con `errors[]` (`field` y `message`). Nunca devuelve el valor enviado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    Locked:
      description: '423 `AUTH_ACCOUNT_LOCKED`: cuenta bloqueada 15 min tras 5 intentos fallidos (SEC-09).'
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    TooManyRequests:
      description: '429 `RATE_LIMITED`: demasiadas peticiones por cuenta o por IP (SEC-09). Incluye `Retry-After`.'
      headers:
        Retry-After:
          description: Segundos que hay que esperar.
          schema:
            type: integer
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'
    ServiceUnavailable:
      description: '503 `INTERNAL_ERROR`: la base de datos no responde.'
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetail'

```

