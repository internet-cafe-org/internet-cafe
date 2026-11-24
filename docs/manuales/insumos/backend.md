# Insumos de Backend para los manuales (BE-22)

Contenido para los manuales del estudiante, del administrador y de TI que redacta el Scrum Master
(SM-01). Los mensajes están copiados del código. Las pantallas y sus capturas las entregan UI (UI-13)
y Desktop (DSK-16).

## 1. Reglas visibles

| Regla | Qué ve la persona | Referencia |
|---|---|---|
| Una sesión activa por estudiante | Si confirma el acceso en otro equipo, la sesión anterior se cierra sola. | RN-03 |
| Una sesión activa por equipo | Si el equipo ya tiene una sesión, al confirmar aparece «Equipo en uso». | RN-04 |
| El QR dura 60 s | El equipo muestra uno nuevo cada 45 s. El anterior sirve hasta cumplir sus 60 s; después aparece «QR vencido». | RF-QR-01, RN-05 |
| El QR sirve una vez | Si otra persona ya lo usó aparece «QR ya utilizado». Si la misma persona repite la confirmación, recibe su misma sesión. | RN-05 |
| Pedir un QR nuevo cierra la sesión del equipo | Si el equipo vuelve a pedir un QR, la sesión que tenía abierta se cierra. | RN-02 |
| Cierre a los 3 min sin latido | Si el equipo se apaga o pierde la red, la sesión se cierra sola después de 3 min. El servidor revisa cada 30 s, así que puede tardar hasta unos 3 min y 30 s. La hora de fin es la del último latido, no la del cierre. | RN-07 |
| Cierre remoto | Si la sesión se cierra desde la web o la cierra un administrador, el equipo se entera en su próximo latido (cada 60 s). | RF-SES-06 |
| Equipo deshabilitado | No muestra QR ni acepta accesos: «Equipo deshabilitado». | RN-08 |
| La hora la fija el servidor | Todas las horas de inicio y fin son del servidor, no del PC ni del teléfono. | RN-01 |
| Contraseña | De 10 a 128 caracteres, sin exigir símbolos. La nueva debe ser distinta de la actual. | RF-AUT-10 |
| Bloqueo por intentos | 5 contraseñas fallidas seguidas bloquean el inicio de sesión 15 min. | SEC-09 |
| Límite de peticiones | Registro, inicio de sesión, confirmación del QR y enrolamiento tienen un límite por minuto. | SEC-09 |
| Código de enrolamiento | Un solo uso y 24 h de vigencia. Se muestra una vez; generar otro invalida el anterior. | BE-13 |

**Motivos de cierre de una sesión** (los que guarda la API; la web puede mostrarlos con otro texto):

| Valor | Significado |
|---|---|
| `user_logout_pc` | El estudiante cerró desde el equipo. |
| `user_logout_web` | El estudiante cerró desde la web. |
| `superseded` | La reemplazó otra sesión o un QR nuevo del equipo. |
| `heartbeat_timeout` | El equipo dejó de comunicarse 3 min. |
| `admin_forced` | La cerró un administrador, o se bloqueó la cuenta, se deshabilitó el equipo o se revocó su clave. |
| `machine_shutdown` | El equipo se apagó. |

## 2. Códigos de error de la API

La API responde los errores en formato RFC 9457 (`application/problem+json`). El manual de soporte
debe guiarse por el campo `code`, que no cambia. «Mensaje de la API» es el campo `detail` por
defecto; algunos casos traen un detalle más preciso (sección 2.2).

### 2.1 Catálogo completo

| `code` | HTTP | Título | Mensaje de la API | Qué hacer |
|---|---|---|---|---|
| `VALIDATION_ERROR` | 422 | Datos inválidos | Corrige los campos indicados. | Corregir los campos marcados. |
| `AUTH_INVALID_CREDENTIALS` | 401 | Credenciales incorrectas | El correo o la contraseña no son correctos. | Revisar los datos. Es el mismo mensaje si la cuenta no existe o está bloqueada por un administrador. |
| `AUTH_EMAIL_NOT_VERIFIED` | 403 | Cuenta sin verificar | Ingresa el código de verificación o pide uno nuevo. | No ocurre en el MVP: la verificación de correo está apagada. |
| `AUTH_ACCOUNT_LOCKED` | 423 | Cuenta bloqueada temporalmente | Demasiados intentos fallidos. Espera 15 minutos. | Esperar 15 min; no hace falta soporte. |
| `AUTH_TOKEN_EXPIRED` | 401 | Sesión vencida | El token de acceso venció. | La web renueva sola. Si no puede, hay que iniciar sesión otra vez. |
| `AUTH_CURRENT_PASSWORD_INVALID` | 401 | Contraseña actual incorrecta | La contraseña actual no es correcta. | Escribir bien la contraseña actual. |
| `FORBIDDEN` | 403 | Acceso denegado | No tienes permisos para este recurso. | La cuenta no tiene ese permiso o está bloqueada. |
| `RATE_LIMITED` | 429 | Demasiadas peticiones | Espera el tiempo indicado en Retry-After e inténtalo de nuevo. | Esperar alrededor de un minuto. |
| `CHALLENGE_NOT_FOUND` | 404 | Código QR inválido | Escanea el código QR del equipo. | Escanear el QR que aparece en el equipo. |
| `CHALLENGE_EXPIRED` | 410 | El código QR expiró | Escanea el código nuevo del equipo. | Escanear el QR nuevo. |
| `CHALLENGE_ALREADY_USED` | 409 | El código QR ya se usó | Escanea el código nuevo del equipo. | Escanear el QR nuevo. |
| `MACHINE_BUSY` | 409 | Equipo ocupado | El equipo ya tiene una sesión activa. Ciérrala y reintenta. | Cerrar la sesión en el equipo y volver a escanear. |
| `MACHINE_DISABLED` | 403 | Equipo deshabilitado | Contacta a soporte. | Usar otro equipo; un administrador debe habilitarlo. |
| `MACHINE_SIGNATURE_INVALID` | 401 | Firma del equipo inválida | La firma de la petición falta, no es válida o está repetida. | TI: el equipo no está enrolado o se revocó su clave. Enrolarlo de nuevo. |
| `MACHINE_CLOCK_SKEW` | 401 | Reloj del equipo desfasado | El reloj del equipo está fuera de la tolerancia permitida. | La app corrige sola. Si persiste, TI ajusta la hora de Windows (tolerancia: 30 s). |
| `ENROLLMENT_CODE_INVALID` | 401 | Código de enrolamiento inválido | Pide un código nuevo al administrador. | El código no existe, se usó o venció. Generar otro. |
| `SESSION_NOT_FOUND` | 404 | Sesión no encontrada | La sesión no existe o no es tuya. | Actualizar la página. |
| `BAD_REQUEST` | 400 | Petición inválida | El servidor no pudo procesar la petición. | Reintentar; si se repite, avisar a soporte. |
| `NOT_FOUND` | 404 | Recurso no encontrado | La ruta solicitada no existe. | Revisar la dirección. |
| `METHOD_NOT_ALLOWED` | 405 | Método no permitido | La ruta no admite este método HTTP. | Error de la aplicación: avisar a soporte. |
| `CONFLICT` | 409 | Conflicto | La operación no es posible en el estado actual del recurso. | Leer el detalle (sección 2.2). |
| `PAYLOAD_TOO_LARGE` | 413 | Cuerpo demasiado grande | El cuerpo de la petición supera el límite permitido. | Enviar menos datos. |
| `INTERNAL_ERROR` | 500 | Error interno | Ocurrió un error inesperado. Inténtalo más tarde. | Reintentar. Si se repite, dar a soporte la cabecera `X-Request-ID`. |

### 2.2 Detalles específicos

| `code` | Detalle | Cuándo |
|---|---|---|
| `CONFLICT` | Ya existe una sala con ese nombre. | Crear o renombrar una sala |
| `CONFLICT` | Ya existe un equipo con ese código. | Crear un equipo |
| `CONFLICT` | El equipo aún no se enroló; no se puede activar. | Activar un equipo pendiente de enrolar |
| `CONFLICT` | No se puede generar un código para un equipo deshabilitado. | Generar un código de enrolamiento |
| `CONFLICT` | Esa clave ya está registrada por otro equipo. | Enrolar un equipo |
| `NOT_FOUND` | La sala no existe. | Administración de salas y equipos |
| `NOT_FOUND` | El equipo no existe. | Administración de equipos |
| `SESSION_NOT_FOUND` | La sesión no existe. | Cierre forzado por el administrador |
| `SESSION_NOT_FOUND` | El equipo no tiene una sesión abierta. | Cierre desde el equipo |
| `VALIDATION_ERROR` | La contraseña nueva debe ser distinta de la actual. | Cambio de contraseña |

### 2.3 Cómo se ve en pantalla

Textos actuales de la web y del escritorio para los errores más comunes. Si UI o Desktop los
cambian, vale el de su insumo.

| Situación | `code` | Texto en pantalla |
|---|---|---|
| Inicio de sesión (web) | `AUTH_INVALID_CREDENTIALS` | «No pudimos iniciar sesión. El correo o la contraseña son incorrectos. Revisa tus datos e inténtalo de nuevo.» |
| Inicio de sesión (web) | `AUTH_ACCOUNT_LOCKED` | «Acceso bloqueado temporalmente. Alcanzaste 5 intentos fallidos. Espera 15 minutos antes de volver a iniciar sesión.» |
| Inicio de sesión (web) | Sin conexión o 5xx | «No pudimos conectar con el servicio. Inténtalo de nuevo en unos minutos.» |
| Cambio de contraseña (web) | `AUTH_CURRENT_PASSWORD_INVALID` | «La contraseña actual no es correcta.» |
| Cambio de contraseña (web) | `VALIDATION_ERROR` | «La nueva contraseña no cumple los requisitos: debe tener entre 10 y 128 caracteres y ser distinta de la actual.» |
| Cambio de contraseña (web) | `RATE_LIMITED` | «Demasiados intentos. Espera unos minutos e inténtalo de nuevo.» |
| Confirmar acceso (web) | `CHALLENGE_EXPIRED` | «QR vencido. Este código QR venció. Escanea el código nuevo que aparece en el equipo.» |
| Confirmar acceso (web) | `CHALLENGE_ALREADY_USED` | «QR ya utilizado. Este código QR ya fue utilizado. Escanea el código nuevo del equipo.» |
| Confirmar acceso (web) | `CHALLENGE_NOT_FOUND` | «QR inválido. Este código no es válido o no pertenece al sistema. Escanea el QR que aparece en el equipo.» |
| Confirmar acceso (web) | `MACHINE_DISABLED` | «Equipo deshabilitado. Este equipo está deshabilitado. Contacta al personal de soporte o utiliza otro equipo.» |
| Confirmar acceso (web) | `MACHINE_BUSY` | «Equipo en uso. Este equipo ya tiene una sesión activa. Cierra la sesión en el equipo y vuelve a escanear.» |
| Confirmar acceso (web) | Otros | «No pudimos completar el acceso. Inténtalo de nuevo en unos minutos o vuelve a escanear el código.» |
| Enrolamiento (escritorio) | 401 | «El código no es válido, ya se usó o venció.» |
| Enrolamiento (escritorio) | 409 | «La clave de este equipo ya está registrada.» |
| Enrolamiento (escritorio) | 422 | «El código o la clave del equipo no cumple el contrato de enrolamiento.» |
| Enrolamiento (escritorio) | 429 | «Se alcanzó el límite de intentos. Espera antes de volver a intentarlo.» |

## 3. CLI de administración

Dos comandos para quien administra el servidor: `create-admin` y `block-user`. Se ejecutan desde la
carpeta `Backend/` con las dependencias instaladas. El workflow `admin-cli` de GitHub llega con QA-18;
mientras tanto se usan así.

### 3.1 Variables de entorno

| Variable | Para qué | Comandos |
|---|---|---|
| `DATABASE_URL` | Conexión a la base del entorno | Los dos |
| `SECRET_KEY` | La exige la configuración de la API al arrancar | Los dos |
| `BLIND_INDEX_KEY` | La misma clave de la API; con otra no se encuentra la cuenta | Los dos |
| `DATA_ENC_KEYS` | La misma de la API, para cifrar el correo y el nombre | `create-admin` |
| `ADMIN_PASSWORD` | Contraseña del administrador (10 a 128 caracteres) | `create-admin` |
| `ADMIN_CLI_EMAIL` | Opcional: el correo, si no se pasa con `--email` | Los dos |

Los valores son secretos: no se escriben en el manual, en capturas ni en el historial de la terminal.
En PowerShell, la contraseña se pide sin mostrarla y se borra al terminar:

```powershell
$clave = Read-Host "Contraseña del administrador" -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new("", $clave).Password
```

```powershell
Remove-Item Env:ADMIN_PASSWORD
```

### 3.2 Crear un administrador

```powershell
python -m tools.admin_cli create-admin --email admin@dominio.edu --nombre "Nombre Apellido"
```

Resultado: `Administrador creado (id <uuid>).` La cuenta queda activa y ya puede iniciar sesión en la
web. La acción queda en la auditoría (`cli.create_admin`).

### 3.3 Bloquear una cuenta

```powershell
python -m tools.admin_cli block-user --email estudiante@dominio.edu
```

Resultado, según el caso:

- `Cuenta <uuid> bloqueada: 2 sesiones web revocadas, acceso <uuid> cerrado.`
- `Cuenta <uuid> bloqueada: 0 sesiones web revocadas, sin acceso activo.`
- `Cuenta <uuid> ya estaba bloqueada: 0 sesiones web revocadas, sin acceso activo.`

Qué pasa al bloquear (RN-12):

1. La persona no puede iniciar sesión: ve el mismo mensaje que con una contraseña incorrecta.
2. Se revocan sus sesiones web. Una página abierta puede conservar su token hasta 10 min, pero no
   puede renovarlo.
3. Se cierra su acceso activo (`admin_forced`); el equipo se entera en su próximo latido.
4. Queda en la auditoría (`cli.block_user`).

Se puede repetir sin error. **Precaución:** el CLI no tiene un comando para desbloquear y también acepta
cuentas de administrador. Antes de bloquear una, comprobar que quede otro administrador activo.

### 3.4 Mensajes de error y códigos de salida

| Mensaje | Salida | Qué hacer |
|---|---|---|
| `ERROR: indica el correo con --email o ADMIN_CLI_EMAIL.` | 2 | Pasar el correo. |
| `ERROR: define BLIND_INDEX_KEY (la misma de la API).` | 2 | Definir la variable. |
| `ERROR: define ADMIN_PASSWORD en el entorno.` | 2 | Definir la variable. |
| `the following arguments are required: --nombre` | 2 | Agregar `--nombre`. |
| `ERROR: El correo no es válido.` | 1 | Revisar el correo. |
| `ERROR: El nombre debe tener entre 1 y 120 caracteres.` | 1 | Revisar el nombre. |
| `ERROR: La contraseña debe tener entre 10 y 128 caracteres.` | 1 | Usar otra contraseña. |
| `ERROR: Ya existe una cuenta con ese correo.` | 1 | La cuenta ya existe; no se modifica. |
| `ERROR: No existe una cuenta con ese correo.` | 1 | Revisar el correo y que `BLIND_INDEX_KEY` sea la del entorno. |

Salida `0`: terminó bien. El CLI nunca muestra el correo ni la contraseña, solo ids. Si falla la
conexión a la base se ve un error de Python y la salida es `1`: revisar `DATABASE_URL` y la red.
