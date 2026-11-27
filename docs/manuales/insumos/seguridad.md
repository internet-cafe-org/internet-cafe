# Insumos de Seguridad y Privacidad para los manuales (SEC-15 · HU-35)

Contenido para los manuales del estudiante y del administrador que redacta el Scrum Master
(SM-01 y SM-02): reglas de contraseña, bloqueo por intentos fallidos, protección de datos personales
y consentimiento. Los parámetros están tomados del SRS y de la implementación del backend.

Las reglas generales y los códigos de error están en `backend.md` (BE-22), y las preguntas
frecuentes de uso en `testing.md` (QA-19).

## 1. Política de contraseña y recuperación de cuenta

| Regla | Qué ve o debe hacer la persona | Referencia |
|---|---|---|
| Longitud de contraseña | Debe tener entre **10 y 128 caracteres**. No se exigen símbolos especiales; se admiten frases largas. Si está fuera de rango, el sistema la rechaza (`422`). | RF-AUT-11 |
| Cambio de contraseña | Al cambiarla desde la cuenta, la nueva contraseña debe ser distinta a la actual. Al guardarla, se cierran las demás sesiones activas. | RF-AUT-10 |
| Verificación y recuperación con OTP | El registro y el restablecimiento de contraseña envían un código de **6 dígitos** al correo institucional con vigencia de **10 minutos** y un solo uso. | ST-SEC-01 |
| Límite de reenvíos de código | Se pueden solicitar máximo **3 códigos OTP por hora** por cuenta. Si se supera, el usuario debe esperar antes de pedir otro (`429`). | ST-SEC-01 |

## 2. Bloqueo tras 5 intentos fallidos

| Escenario | Qué ocurre y cómo se resuelve | Código de error |
|---|---|---|
| 5 contraseñas incorrectas seguidas | La cuenta se bloquea temporalmente durante **15 minutos**. Durante ese tiempo, incluso si se ingresa la contraseña correcta, el acceso sigue bloqueado hasta cumplir los 15 minutos. | `AUTH_ACCOUNT_LOCKED` (`423`) |
| 5 códigos OTP incorrectos | El código OTP actual queda invalidado al quinto intento fallido. El usuario debe solicitar un código nuevo (`resend-code` o `forgot`). | `OTP_MAX_ATTEMPTS` |
| Límite de peticiones por minuto | Si se realizan demasiados intentos seguidos en rutas de autenticación o escaneo QR (más de **10 peticiones por minuto** por cuenta o IP), el sistema frena temporalmente las solicitudes. | `429 Too Many Requests` |
| Bloqueo administrativo | Un administrador puede suspender o desbloquear una cuenta manualmente desde el panel de usuarios (`Admin · Usuarios`), cerrando de inmediato sus sesiones activas. | `admin_forced` |

## 3. Qué datos se guardan y cómo se protegen

| Dato | Cómo se almacena y protege | Qué implica para el usuario |
|---|---|---|
| Correo institucional, nombre completo y código estudiantil | Se guardan **cifrados en la base de datos con AES-256-GCM** (`email_ct`, `full_name_ct`, `student_code_ct`) a nivel de aplicación, con llaves separadas de la base de datos. | Nadie que acceda directamente a las tablas de la base de datos puede leer los datos personales en texto claro. Las búsquedas administrativas operan solo por coincidencia exacta mediante *blind index* HMAC-SHA256. |
| Contraseña | Nunca se guarda en texto plano ni cifrada reversiblemente: se almacena únicamente un **hash unidireccional Argon2id** (parámetros OWASP: 19 MiB, 2 iteraciones). | Nadie (ni administradores ni desarrolladores) puede ver ni recuperar la contraseña actual de un usuario; solo puede restablecerse mediante OTP. |
| Códigos OTP y tokens de sesión | Se almacenan únicamente como **hashes HMAC / SHA-256** (`code_hash`, `token_hash`). El contenido del correo en cola (`payload_ct`) viaja cifrado y se anula una vez enviado. | Los códigos no quedan expuestos en registros técnicos (*logs*) ni en la cola de correos después de enviarse. |
| Tráfico en red y conexión a base de datos | Todo el tráfico viaja cifrado por **HTTPS (TLS 1.2 o superior; TLS 1.3 en escritorio)** y la base de datos exige conexión SSL (`sslmode=require`). | Evita la interceptación de credenciales, códigos OTP o tokens QR en la red del café internet. |

## 4. Consentimiento y privacidad del usuario

| Aspecto | Regla aplicada en el sistema | Referencia |
|---|---|---|
| Consentimiento explícito obligatorio | Durante el registro (`W-02`), el usuario debe aceptar explícitamente el tratamiento de sus datos personales antes de crear la cuenta. El sistema registra la fecha y hora exacta de aceptación (`privacy_consent_at` no nulo). | RNF-PRI-01 |
| Minimización de datos | Solo se solicitan los datos estrictamente necesarios para identificar al estudiante y registrar su acceso a los equipos: correo institucional, código estudiantil y nombre completo (opcional en administradores). | RNF-PRI |
| Trazabilidad sin exposición de secretos | Las acciones relevantes de seguridad (inicios de sesión, bloqueos, cambios de contraseña, solicitudes de OTP) quedan registradas en auditoría (`audit_logs`) sin almacenar contraseñas, códigos OTP ni datos personales en texto plano. | SEC-08 |
