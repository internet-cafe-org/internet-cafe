# Contrato de Backend y Especificación de Datos / OpenAPI v0.2 (BE-18) - Sprint 2

> Fuente de verdad: el bloque YAML de este documento es idéntico a `openapi.yaml`.
> Estado: **borrador para aprobación** de los líderes y de Seguridad (DoD de BE-18).

## 1. Objetivo del Módulo
Contrato técnico y de datos de la API REST del sistema Internet Café, acordado con los equipos de UI, Desktop y Seguridad. La v0.2 se entrega en dos partes:

| Entrega | Contenido |
|---|---|
| **Lunes 02/11** | Latido del equipo con `mode` y estado de sesión; sesión actual del equipo; cierres (`user_logout_pc`, `machine_shutdown`, y el aviso de cierres remotos por latido). |
| **Martes 03/11** | `/me` (perfil, historial, sesión activa, cierre propio); administración (salas, equipos, sesiones y cierre forzado); firma por petición del equipo. |

## 2. Cambios respecto a v0.1
- **Nuevo** `POST /machine/heartbeat`, `GET /machine/sessions/current`, `POST /machine/sessions/current/end`.
- **Nuevo** `GET /me`, `GET /me/sessions`, `GET /me/sessions/active`, `POST /me/sessions/{id}/end`.
- **Nuevo** `GET|POST /admin/labs`, `GET /admin/machines`, `PATCH /admin/machines/{id}`, `GET /admin/sessions`, `POST /admin/sessions/{id}/end`.
- **Nuevo** código de error genérico `CONFLICT` (409). Los demás vienen del catálogo del SRS §10.5.
- `ProblemDetails` pasa a llamarse `ProblemDetail` y es el único esquema de error (antes convivían los dos nombres); se añade `FieldError`.
- Sin cambios: `/registro`, `/enroll`, `/credencial-provisional`, `/long-poll`, `/machine/challenges`, `/machine/challenges/wait`, `/scan/preview`, `/scan/claim`.

## 3. Autenticación y firma del equipo
| Esquema | Rutas | Detalle |
|---|---|---|
| `bearerAuth` | `/me/*`, `/admin/*` | Access token ES256 de 10 min. `/admin/*` exige `role = admin` (`FORBIDDEN` si no). |
| `machineSignature` | endpoints del equipo (objetivo) | RFC 9421 con `@method`, `@target-uri` y `content-digest` (RFC 9530). `created` ±30 s (`MACHINE_CLOCK_SKEW`); nonce no repetido en 60 s; firma ausente, inválida o repetida → `MACHINE_SIGNATURE_INVALID`. |
| `machineProvisional` | endpoints del equipo (transitorio) | `X-Machine-Code` + `X-Machine-Key`. El servidor guarda solo el SHA-256 y compara en tiempo constante. Se retira cuando Seguridad active la firma. |

Los routers no cambian al activar la firma: solo se reemplaza la dependencia `require_machine`.

## 4. Latido y cierres (entrega del lunes)
- `POST /machine/heartbeat` (cada 60 s): `{ "server_time", "mode", "session_status", "session_id?", "end_reason?" }`.
  `session_status`: `active` | `ended` | `none`. El equipo envía `session_id` con la sesión que cree tener; si ya cerró, recibe `ended` y el `end_reason`, que es como se entera de un cierre remoto (web, administrador o reemplazo).
- Motivos de cierre (`end_reason`): `user_logout_pc`, `user_logout_web`, `superseded`, `heartbeat_timeout`, `admin_forced`, `machine_shutdown`.
- Un cierre es atómico e idempotente: el primero gana y un reintento devuelve el estado final sin error.
- Sin latido durante 3 min la API cierra la sesión con `ended_at = last_heartbeat_at` (RN-07; tarea periódica).

## 5. Formato de errores (QA-03)
- Todos los errores salen como `application/problem+json` con el esquema `ProblemDetail`.
- `type` se arma con `ERRORS_BASE_URL` más el `code` en kebab-case (`CHALLENGE_EXPIRED` → `/challenge-expired`).
- Los 422 llevan `code: VALIDATION_ERROR` y `errors[]` con `field` y `message`. No devuelven `input` ni `ctx`, para no repetir contraseñas u otros datos del cliente. Los cuerpos de /machine/heartbeat, /me y /admin rechazan campos desconocidos.
- Además del catálogo del SRS §10.5 existen los códigos genéricos `BAD_REQUEST`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `INTERNAL_ERROR` y `CONFLICT`.
- Un 500 no incluye la traza; el servidor registra un `request_id` que viaja en la cabecera `X-Request-ID`.
- Ninguna respuesta incluye contraseñas, hashes, tokens, claves del equipo ni el código de estudiante completo (siempre `student_code_masked`).

## 6. Especificación OpenAPI v0.2.0
```yaml
openapi: 3.0.3
info:
  title: Internet Cafe API - Contrato
  version: 0.2.0
  description: 'Contrato de datos y endpoints. v0.2 (BE-18): latido con `mode`, sesión actual y cierres del equipo;
    /me; administración; firma por petición del equipo. Los endpoints de v0.1 no cambian.'
paths:
  /api/v1/registro:
    post:
      summary: Registro inicial de usuario o dispositivo
      description: Inicia el proceso de registro devolviendo un código 202 indicando aceptación para procesamiento
        asíncrono.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
              - identificacion
              - correo
              - rol
              properties:
                identificacion:
                  type: string
                  example: '123456789'
                correo:
                  type: string
                  format: email
                  example: usuario@ejemplo.com
                rol:
                  type: string
                  example: cliente
      responses:
        '202':
          description: Solicitud aceptada y en proceso.
          content:
            application/json:
              schema:
                type: object
                properties:
                  estado:
                    type: string
                    example: procesando
                  mensaje:
                    type: string
                    example: Registro aceptado para procesamiento en segundo plano
  /api/v1/enroll:
    post:
      summary: Enrolamiento con JWK y prueba de posesión
      description: Valida la clave pública JSON Web Key y la prueba criptográfica de posesión.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
              - jwk
              - prueba_posesion
              properties:
                jwk:
                  type: object
                  description: Estructura de clave pública JSON Web Key (RFC 7517).
                  example:
                    kty: RSA
                    n: '...'
                    e: AQAB
                prueba_posesion:
                  type: string
                  description: Firma criptográfica firmada con la clave privada correspondiente.
                  example: eyJhbGciOiJSUzI1NiIs...
      responses:
        '200':
          description: Enrolamiento completado con éxito.
          content:
            application/json:
              schema:
                type: object
                properties:
                  estado:
                    type: string
                    example: enrolado
                  dispositivo_id:
                    type: string
                    example: dev-98765
  /api/v1/credencial-provisional:
    get:
      summary: Emisión de credencial provisional
      description: Entrega una credencial temporal bajo validación de seguridad previa.
      parameters:
      - in: header
        name: X-Device-ID
        required: true
        schema:
          type: string
      responses:
        '200':
          description: Credencial provisional generada correctamente.
          content:
            application/json:
              schema:
                type: object
                properties:
                  credencial_temporal:
                    type: string
                    example: temp-token-xyz-789
                  expiracion_segundos:
                    type: integer
                    example: 300
  /api/v1/long-poll:
    get:
      summary: Canal de sondeo largo (Long-Poll)
      description: Mantiene la conexión abierta hasta que ocurra un evento relevante para el cliente.
      parameters:
      - in: query
        name: ultimo_evento_id
        required: false
        schema:
          type: string
      responses:
        '200':
          description: Evento recibido satisfactoriamente.
          content:
            application/json:
              schema:
                type: object
                properties:
                  evento_id:
                    type: string
                    example: evt-456
                  tipo:
                    type: string
                    example: sesion_autorizada
                  datos:
                    type: object
                    example:
                      terminal: PC-05
                      tiempo_restante: 3600
  /api/v1/machine/challenges:
    post:
      summary: Generar un reto QR para una máquina
      description: Crea un reto QR de un solo uso para el equipo identificado. Máximo 2 retos vigentes por equipo
        (RN-06).
      parameters:
      - in: header
        name: x-machine-code
        required: true
        schema:
          type: string
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
      summary: Espera en long-poll de la aprobación de un reto QR
      description: Mantiene la conexión abierta hasta que un estudiante reclame el reto QR del equipo o venza el
        timeout.
      parameters:
      - in: header
        name: x-machine-code
        required: true
        schema:
          type: string
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
      summary: Consultar vista previa de un reto QR
      description: Obtiene información del equipo antes de confirmar el acceso. No consume el reto.
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
  /api/v1/scan/claim:
    post:
      summary: Confirmar acceso escaneando el QR (Claim)
      description: Reclama el reto QR y crea la sesión de acceso para el estudiante de forma atómica.
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
  /api/v1/admin/machines:
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
```


## 3. Formato de errores (QA-03)

- Todos los errores salen como `application/problem+json` con el esquema `ProblemDetail`.
- `type` se arma con `ERRORS_BASE_URL` más el `code` en kebab-case (`CHALLENGE_EXPIRED` → `/challenge-expired`).
- Los 422 llevan `code: VALIDATION_ERROR` y `errors[]` con `field` y `message`. No devuelven `input` ni `ctx`, para no repetir contraseñas u otros datos del cliente.
- Además del catálogo del SRS §10.5 existen los códigos genéricos `BAD_REQUEST`, `NOT_FOUND`, `METHOD_NOT_ALLOWED` e `INTERNAL_ERROR`.
- Un 500 no incluye la traza; el servidor registra un `request_id` que viaja en la cabecera `X-Request-ID`.

## Sesion web: refresh y logout (SEC-03a)

El refresh token viaja en la cookie `refresh_token` (HttpOnly, Secure, SameSite=Strict, Path=/api/v1/auth, 7 dias). Nunca se devuelve en el cuerpo. El access token se entrega en el cuerpo y el cliente lo guarda en memoria.

| Metodo y ruta | Descripcion | Respuestas |
|---|---|---|
| POST /api/v1/auth/refresh | Rota el refresh token (revoca el usado y emite uno nuevo en la misma familia) y devuelve `{access_token, token_type, expires_in}` | 200; 401 `AUTH_INVALID_CREDENTIALS` (sin cookie, desconocido, revocado o reutilizado); 401 `AUTH_TOKEN_EXPIRED` (vencido); 403 `FORBIDDEN` (Origin no permitido) |
| POST /api/v1/auth/logout | Revoca la familia del token y borra la cookie. Idempotente | 204; 403 `FORBIDDEN` (Origin no permitido) |

Si se presenta un refresh token ya revocado se considera robo y se revoca toda la familia.

