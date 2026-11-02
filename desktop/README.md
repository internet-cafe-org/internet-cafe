# Desktop identity

This Java 21 desktop component implements HU-08 / DSK-03a. It creates an
ECDSA P-256 key pair, stores the private key and self-signed certificate in
`%ProgramData%\InternetCafe\machine-identity.p12`, and exposes the public key as an EC P-256 JWK
with its RFC 7638 SHA-256 thumbprint. Existing identities are loaded rather than replaced.

On Windows, the module sets an ACL granting full control to the directory/file owner and Local
System, and to Administrators when the group is resolvable. The `Users` group gets read-only
access so the desktop can use the identity under a standard account; if Windows cannot resolve
that group, read-only access is granted to Authenticated Users instead. The JWK contains only
`crv`, `kty`, `x`, and `y`; the private key remains in the PKCS12 store. The keystore password is
supplied by the caller and is not embedded in the source.

Run the unit tests from this directory with `gradle test`.

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
| `POST /api/v1/enroll` | 200 `{estado, dispositivo_id}` |
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