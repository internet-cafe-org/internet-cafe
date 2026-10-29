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