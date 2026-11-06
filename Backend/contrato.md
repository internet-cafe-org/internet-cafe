# Contrato de Backend y Especificación de Datos / OpenAPI v0.1 (BE-01) - Sprint 1

## 1. Objetivo del Módulo
Establecer el contrato técnico y de datos de la API REST del sistema Internet Café para el Sprint 1, acordado formalmente con los equipos de UI, Desktop y Seguridad.

## 2. Especificación OpenAPI v0.1 y Contratos de Datos

```yaml
openapi: 3.0.3
info:
  title: Internet Cafe API - Contrato
  version: 0.1.0
  description: Contrato de datos y endpoints para registro asíncrono, enrolamiento con JWK, credenciales provisionales y long-polling.

paths:
  /api/v1/registro:
    post:
      summary: Registro inicial de usuario o dispositivo
      description: Inicia el proceso de registro devolviendo un código 202 indicando aceptación para procesamiento asíncrono.
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
                  example: "123456789"
                correo:
                  type: string
                  format: email
                  example: "usuario@ejemplo.com"
                rol:
                  type: string
                  example: "cliente"
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
                    example: "procesando"
                  mensaje:
                    type: string
                    example: "Registro aceptado para procesamiento en segundo plano"

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
                  example: {"kty": "RSA", "n": "...", "e": "AQAB"}
                prueba_posesion:
                  type: string
                  description: Firma criptográfica firmada con la clave privada correspondiente.
                  example: "eyJhbGciOiJSUzI1NiIs..."
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
                    example: "enrolado"
                  dispositivo_id:
                    type: string
                    example: "dev-98765"

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
                    example: "temp-token-xyz-789"
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
                    example: "evt-456"
                  tipo:
                    type: string
                    example: "sesion_autorizada"
                  datos:
                    type: object
                    example: {"terminal": "PC-05", "tiempo_restante": 3600}


  /api/v1/machine/challenges:
    post:
      summary: Generar un reto QR para una máquina
      description: Crea un reto QR de un solo uso para el equipo identificado.
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
                  challenge_id:
                    type: string
                    format: uuid
                  qr_url:
                    type: string
                    format: uri
                  expires_at:
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
      description: Mantiene la conexión abierta hasta que un estudiante reclame el reto QR del equipo o venza el timeout.
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
                      id:
                        type: string
                        format: uuid
                      status:
                        type: string
                        example: "active"
                      started_at:
                        type: string
                        format: date-time
                  user:
                    type: object
                    required:
                      - full_name
                      - student_code_masked
                    properties:
                      full_name:
                        type: string
                        example: "Ana Pérez"
                      student_code_masked:
                        type: string
                        example: "2021****34"
                  recent_accesses:
                    type: array
                    items:
                      type: object
                      properties:
                        machine_code:
                          type: string
                        lab:
                          type: string
                        started_at:
                          type: string
                          format: date-time
                        ended_at:
                          type: string
                          format: date-time
                        duration_s:
                          type: integer
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'

  /api/v1/scan/preview:
    post:
      summary: Consultar vista previa de un reto QR
      description: Obtiene información del equipo antes de confirmar el acceso.
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
                  expires_at:
                    type: string
                    format: date-time
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
              schema:
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
                      id:
                        type: string
                        format: uuid
                      status:
                        type: string
                        example: "active"
                      started_at:
                        type: string
                        format: date-time
                      machine:
                        type: object
                        required:
                          - id
                          - code
                          - lab
                        properties:
                          id:
                            type: string
                            format: uuid
                          code:
                            type: string
                          lab:
                            type: string
        '200':
          description: Reintento idempotente exitoso (devuelve la sesión existente).
          content:
            application/json:
              schema:
                type: object
                properties:
                  session:
                    type: object
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          $ref: '#/components/responses/Conflict'
        '410':
          $ref: '#/components/responses/Gone'

components:
  schemas:
    ProblemDetails:
      type: object
      description: Formato de error conforme a RFC 9457.
      properties:
        type:
          type: string
          format: uri-reference
          default: about:blank
        title:
          type: string
        status:
          type: integer
        detail:
          type: string
        instance:
          type: string
          format: uri-reference
        code:
          type: string
          description: Código identificador del error.

  responses:
    Unauthorized:
      description: No autorizado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetails'
    Forbidden:
      description: Acceso prohibido.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetails'
    NotFound:
      description: Recurso no encontrado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetails'
    Conflict:
      description: Conflicto con el estado actual del recurso.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetails'
    Gone:
      description: Reto QR expirado.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/ProblemDetails'
```


---

## Endpoints del Estudiante — BE-11 (Sprint 2)

Los siguientes endpoints están disponibles bajo el prefijo `/api/v1` y requieren un
Bearer token ES256 válido en el header `Authorization`.

```yaml
paths:
  /me:
    get:
      summary: Perfil del estudiante autenticado
      tags: [estudiante]
      security:
        - BearerAuth: []
      responses:
        '200':
          description: Datos del perfil. El código de estudiante aparece enmascarado.
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
                  full_name:
                    type: string
                    example: "Juan Pérez"
                  student_code_masked:
                    type: string
                    example: "2021*****34"
                    description: >
                      Código de estudiante con los dígitos centrales ocultos
                      (SRS §9.1 / RNF-PRI-02). Nunca se devuelve el código completo.
                  role:
                    type: string
                    enum: [student, admin]
                  status:
                    type: string
                    enum: [pending_verification, active, blocked]
                  created_at:
                    type: string
                    format: date-time
        '401':
          $ref: '#/components/responses/Unauthorized'

  /me/sessions:
    get:
      summary: Historial de sesiones del estudiante (paginado)
      tags: [estudiante]
      security:
        - BearerAuth: []
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            default: 1
            minimum: 1
        - name: page_size
          in: query
          schema:
            type: integer
            default: 20
            minimum: 1
            maximum: 100
      responses:
        '200':
          description: Lista paginada de sesiones.
          content:
            application/json:
              schema:
                type: object
                properties:
                  page:
                    type: integer
                  page_size:
                    type: integer
                  total:
                    type: integer
                  items:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                          format: uuid
                        machine:
                          type: object
                          properties:
                            id:
                              type: string
                              format: uuid
                            code:
                              type: string
                            lab:
                              type: string
                              nullable: true
                        started_at:
                          type: string
                          format: date-time
                        ended_at:
                          type: string
                          format: date-time
                          nullable: true
                        end_reason:
                          type: string
                          nullable: true
                          enum:
                            - user_logout_pc
                            - user_logout_web
                            - superseded
                            - heartbeat_timeout
                            - admin_forced
                            - machine_shutdown
        '401':
          $ref: '#/components/responses/Unauthorized'

  /me/sessions/active:
    get:
      summary: Sesión de acceso activa del estudiante
      tags: [estudiante]
      security:
        - BearerAuth: []
      responses:
        '200':
          description: Sesión activa en curso.
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
                  machine:
                    type: object
                    properties:
                      id:
                        type: string
                        format: uuid
                      code:
                        type: string
                      lab:
                        type: string
                        nullable: true
                  started_at:
                    type: string
                    format: date-time
                  last_heartbeat_at:
                    type: string
                    format: date-time
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          description: El estudiante no tiene ninguna sesión activa en este momento.
          content:
            application/problem+json:
              schema:
                $ref: '#/components/schemas/ProblemDetails'
              example:
                code: NO_ACTIVE_SESSION
                detail: El estudiante no tiene ninguna sesión activa.

  /me/sessions/{session_id}/end:
    post:
      summary: Cerrar sesión desde el portal web
      tags: [estudiante]
      security:
        - BearerAuth: []
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Sesión cerrada correctamente.
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
                  ended_at:
                    type: string
                    format: date-time
                  end_reason:
                    type: string
                    example: "user_logout_web"
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          description: La sesión pertenece a otro usuario.
          content:
            application/problem+json:
              schema:
                $ref: '#/components/schemas/ProblemDetails'
              example:
                code: SESSION_FORBIDDEN
                detail: No puedes cerrar la sesión de otro usuario.
        '404':
          $ref: '#/components/responses/NotFound'
        '409':
          description: La sesión ya fue cerrada antes.
          content:
            application/problem+json:
              schema:
                $ref: '#/components/schemas/ProblemDetails'
              example:
                code: SESSION_ALREADY_ENDED
                detail: La sesión ya fue cerrada anteriormente.
```
