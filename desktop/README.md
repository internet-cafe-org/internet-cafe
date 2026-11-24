# Desktop identity

This Java 21 desktop component implements HU-08 / DSK-03a and DSK-03b. It creates an
ECDSA P-256 key pair, stores the private key and self-signed certificate in
`%ProgramData%\InternetCafe\machine-identity.p12`, and exposes the public key as an EC P-256 JWK
with its RFC 7638 SHA-256 thumbprint. Existing identities are loaded rather than replaced.

On Windows, the module sets an ACL granting full control to the directory/file owner and Local
System, and to Administrators when the group is resolvable. The `Users` group gets read-only
access so the desktop can use the identity under a standard account; if Windows cannot resolve
that group, read-only access is granted to Authenticated Users instead. The JWK contains only
`crv`, `kty`, `x`, and `y`; the private key remains in the PKCS12 store. Desktop creates a random
keystore password and protects it with Windows DPAPI for the current Windows account.

Run the unit tests from this directory with `gradle test`.

## Equipo enrollment (DSK-03b)

Run the app with `--enroll` from an elevated terminal, for example:

```
gradle run --args=--enroll
```

In the screen, enter the one-time code supplied by TI. The client signs its exact UTF-8 bytes with
the local P-256 private key and sends the public JWK plus the `r||s` proof to
`POST /api/v1/machine/enroll`. On success, the response's machine code, lab, mode and key
thumbprint are saved in `%LOCALAPPDATA%\InternetCafe\enrollment.bin`, encrypted with Windows DPAPI
for the current user. The API returns no credential: every request is signed with the key. The key
password is stored separately in the same profile, also protected with DPAPI.

Run enrollment and the desktop app as the same Windows account; do not enter another account's
credentials at the UAC prompt. The API response assigns the machine code, lab and mode, so the
screen does not accept a room value from the operator. Enrollment requires Windows administrator
privileges and a working API connection.

## QR rotation (DSK-05a)

The QR screen requests a new challenge from `POST /api/v1/machine/challenges`
a few seconds before `rotate_after_s` elapses (default margin: 5 seconds), so the
code on screen stays valid. On success the QR image is regenerated and the
countdown restarts from the new `rotate_after_s`. Backend errors are retried a
limited number of times (default: 3); the last valid QR stays visible until it
expires, and the scheduler does not loop forever. Closing the QR screen stops
the rotation thread. Challenge URLs and tokens are not written to logs.

## Local mock API (DSK-07)

Lets you run the desktop app without the real backend. From this directory:

```
gradle mockApi
```

It listens on `http://127.0.0.1:8000`, the client's default base URL (`API_BASE_URL` or
`-Dapi.base.url`). To use another port set `MOCK_API_PORT` (PowerShell:
`$env:MOCK_API_PORT = "8001"`). To make the long-poll wait before answering, instead of
replying immediately, set `MOCK_LONG_POLL_DELAY_MS` (for example `5000`).

| Endpoint | Response |
| --- | --- |
| `GET /healthz` | 200 `{status, service}` |
| `POST /api/v1/registro` | 202 `{estado, mensaje}` |
| `POST /api/v1/machine/enroll` | 201 `{machine_id, code, lab, mode, keyid}` |
| `GET /api/v1/credencial-provisional` (header `X-Device-ID`) | 200 `{credencial_temporal, expiracion_segundos}` |
| `GET /api/v1/long-poll?ultimo_evento_id=...` | 200 `{evento_id, tipo, datos}` |
| `POST /api/v1/machine/challenges` (header `X-Machine-Code`) | 201 `{challenge_id, qr_url, expires_at, rotate_after_s}` |

The values come from the examples in `Backend/contrato.md`. `/healthz` and
`/api/v1/machine/challenges` are not in that contract (v0.1), so their shapes were taken from the
real backend (`Backend/app/`). A 404 (unknown path), 405 (wrong method) and 400 (missing required
header) are conventions of the mock, because the contract only defines successful responses. The
mock never writes bodies, headers or query strings to its log. The code lives in
`src/test/java/org/internetcafe/desktop/mock/`, and the happy-path JUnit test is
`MockApiServerTest`, run with `gradle test`.
## Espera del escaneo (DSK-05b)

Después de mostrar el QR, el escritorio hace long-poll a `GET /api/v1/machine/challenges/wait` (cabecera `X-Machine-Code`, `timeout=25`) en un hilo virtual (`ChallengeWaitService`).

| Estado | Significado |
|---|---|
| IDLE | Creado, todavía sin iniciar. |
| WAITING | Hay una petición en curso. Si responde `waiting` se vuelve a consultar; si falla la red se reintenta con espera creciente (1 s hasta 10 s). |
| APPROVED | El backend respondió `approved`: se detiene la rotación del QR y se muestra el tablero con el nombre y el código enmascarado. |
| STOPPED | Se canceló desde la pantalla (por ejemplo, al volver). |

Con la API simulada (`MockApiServer`) este endpoint todavía no existe, así que el escritorio reintentará en segundo plano.

## Conexión segura (DSK-13)

El cliente HTTP del escritorio (`SecureHttpClient`) no usa el almacén de certificados del sistema:

- Confía solo en las raíces de `src/main/resources/truststore/` (ISRG Root X1/X2 de Let's Encrypt y GTS Root R1-R4 de Google Trust Services, las autoridades que usa Render).
- Ignora el proxy del sistema (conexión directa).
- Solo negocia TLS 1.3.

Si Render cambia de autoridad, agregar la nueva raíz pública (`.pem`) a esa carpeta y a la lista de `SecureHttpClient`.

## Firma de peticiones del equipo (DSK-12b)

Las peticiones del equipo que usan `/api/v1/machine/challenges`, `/api/v1/machine/challenges/wait`,
`/api/v1/machine/heartbeat` y `/api/v1/machine/sessions/current/end` deben estar protegidas con
RFC 9421 y el perfil `ecdsa-p256-sha256`, etiqueta `sig1`. El contenido y la URL firmada deben
mantenerse idénticos a los enviados por el cliente. Cada intento usa un nonce nuevo y el reloj
ajustado por la cabecera `Date` cuando el servidor indica desfase. Las peticiones con cuerpo incluyen
`Content-Digest`; los GET y el POST vacío de desafíos no incluyen ese digest. La firma es la única
autenticación: un token responde 401 (SEC-14).

El cliente no puede continuar sin el enrolamiento local, su contraseña protegida, el thumbprint
correcto ni el `keyid` guardado. El endpoint de enrolamiento conserva su propia
prueba de posesión y no usa esta firma de máquina. Para Render dev, configura `API_BASE_URL` con el
origen público que coincide con `PUBLIC_API_BASE_URL` del backend y usa un equipo enrolado de prueba.

## Modo kiosco (DSK-11)

En modo kiosco, la ventana ocupa toda la pantalla, permanece encima y no acepta solicitudes para
cerrarse. Los intentos de minimizarla se revierten mientras está bloqueada. El bloqueo se libera
mientras hay una sesión activa, tras tres minutos sin respuesta de la API o mientras el equipo está
en modo pasivo. Cuando la API responde de nuevo, el kiosco vuelve a bloquear la ventana si no hay
una sesión activa.

Windows no permite que JavaFX bloquee de forma confiable atajos seguros como `Ctrl+Alt+Supr`, la
tecla Windows o el cambio a otra aplicación. Esta limitación está aceptada para el MVP; el kiosco
no instala interceptores de teclado ni intenta eludir controles de seguridad del sistema operativo.

## Latido y cierre remoto (DSK-08)

- `HeartbeatService` envía `POST /api/v1/machine/heartbeat` cada 60 s, siempre, con o sin sesión, con el `session_id` que el equipo cree tener.
- Si el servidor responde `ended`, el equipo registra el cierre remoto en el log (sesión, motivo y hora) y vuelve al QR. Con un timeout de 5 s por latido, el cierre se detecta en 65 s o menos.
- El botón "Cerrar sesión" del tablero llama a `POST /api/v1/machine/sessions/current/end` (motivo `user_logout_pc`) y vuelve al QR.
- Los latidos fallidos solo se registran; no cierran la sesión local (el servidor la cierra a los 3 min sin latido).

## Cierre al apagar (HU-34)

Al terminar la JVM, si `HeartbeatService` todavía registra una sesión activa, un shutdown hook
intenta cerrar la sesión con el motivo `machine_shutdown`. La llamada tiene un timeout de 3 s; si
el equipo ya perdió la red o el proceso no puede completar el cierre, el cierre por inactividad de
la API sigue siendo el respaldo. El log solo registra la clase de excepción, nunca el identificador
de sesión.

## Prototipo de clave con TPM (ST-DSK-01)

`TpmKeyPrototype`, dentro del paquete `identity`, prueba una clave P-256 no exportable del almacén
de Windows mediante SunMSCAPI. El informe y los pasos de reproducción están en
`docs/desktop/ST-DSK-01-tpm-sunmscapi.md`. Esta integración es solo experimental: todavía no
forma parte de `MachineIdentityStore` ni reemplaza el almacén de identidad usado por el enrolamiento.
