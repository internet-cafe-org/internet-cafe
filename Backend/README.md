# Internet Café — Backend (contrato v0.2)

FastAPI + SQLAlchemy async + PostgreSQL (Neon). Errores RFC 9457 (`application/problem+json`) vía `app/error_handlers.py`:
sin `input`, credenciales, tokens ni trazas en las respuestas.

- Configuración: copia `.env.example` → `.env` (valores ficticios; nunca secretos reales).
- Base de datos y roles: ver `db/README.md`.
- Contrato: `openapi.yaml` / `contrato.md` (v0.2.1).
- Pruebas: `python -m pytest`.

## Correo transaccional (ST-BE-01)

`app.services.outbox.encolar_correo` agrega la fila cifrada a la sesión del evento. El llamador confirma
esa misma transacción. La autenticación usa este encolador para la verificación, la recuperación
y el aviso de cambio de contraseña. Las plantillas de OTP reciben `codigo` y `vence_en` con zona horaria.

El trabajador arranca con la API cuando están configurados `RESEND_API_KEY`, `EMAIL_FROM` y
`DATA_ENC_KEYS`. Configura un remitente del dominio verificado y una llave de Resend de solo envío
en el entorno. La prueba de integración usa PostgreSQL de pruebas y un transporte HTTP simulado.

El trabajador conserva el UUID del correo como clave de idempotencia. Reintenta fallos transitorios
después de 1, 5, 30 y 30 minutos, hasta cinco intentos. Vuelve a reclamar envíos interrumpidos al
vencer su reserva y descarta los OTP vencidos. Elimina el contenido cifrado al finalizar la entrega
o agotar los reintentos. Los reintentos se limitan a la ventana de idempotencia de Resend de 24 horas.

## Concurrencia (BE-05 / BE-07b)
Orden de bloqueos fijo: fila del equipo `FOR UPDATE` → retos → sesiones. Las cancelaciones de retos son `UPDATE` masivos con
`WHERE status = 'pending'`, así un reto `approved` nunca se pisa.

## Administración de cuentas por CLI (BE-20)
Desde `Backend/`, con `DATABASE_URL` y `BLIND_INDEX_KEY` (la misma de la API) en el entorno:

```bash
ADMIN_PASSWORD=... python -m tools.admin_cli create-admin --email admin@dominio --nombre "Nombre Apellido"
python -m tools.admin_cli block-user --email estudiante@dominio
```

- `create-admin` crea el administrador inicial. La contraseña solo se lee de `ADMIN_PASSWORD` (10 a 128 caracteres).
- `block-user` cumple RN-12: deja la cuenta en `blocked`, revoca todos sus refresh tokens y cierra su acceso activo con
  `admin_forced` (el PC se entera en su próximo latido). Se puede repetir sin error.
- El correo puede ir en `ADMIN_CLI_EMAIL` en lugar de `--email`. La salida solo muestra ids, nunca el correo ni la contraseña.
- Salida: `0` bien, `1` error de datos (cuenta inexistente o repetida, contraseña corta), `2` falta configuración.
- En GitHub la ejecuta el workflow `admin-cli` (QA-18).

## Preparación de la carga de dev (BE-19a)

Desde `Backend/` en PowerShell, con Python 3.12 y `DATABASE_URL` del proyecto Neon **dev**
(rol `svc_app`) cargada por el gestor de secretos. La base debe estar migrada.

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r tools/carga/requirements.txt
$env:APP_ENV = 'dev'
$env:SECRET_KEY = 'no-se-usa-en-la-semilla'
& $python -m tools.carga.datos
```

La semilla crea 300 equipos activos en `Sala Dev Locust` y guarda sus claves públicas en dev.
Conserva el archivo privado `.env.locust.json` para repetir la preparación y ejecutar Locust
desde este directorio. Git ya ignora el archivo. Al repetir con las mismas claves, la semilla
reutiliza los equipos existentes y aborta si encuentra un conflicto.

Para BE-19b, configura `RATE_LIMIT_ENABLED=false` temporalmente en el servicio **dev** de Render
(exactamente `false`, sin comillas ni espacios: con otro valor la API no arranca y Render sigue
sirviendo la versión anterior con el límite encendido) y comprueba que el despliegue esté activo
con `MACHINE_AUTH_MODE=signature`. Usa el mismo origen
que `PUBLIC_API_BASE_URL` y un reloj sincronizado. Ejemplo desde la misma terminal:

```powershell
& $python -m locust -f tools/carga/locustfile.py --headless `
  --host https://internet-cafe-tq03.onrender.com -u 300 -r 10 -t 5m `
  --stop-timeout 35 --csv "$env:TEMP\locust-dev"
```

Cada usuario usa una identidad distinta, envía un latido inicial y luego uno cada 60 segundos.
En paralelo hace long-poll de 25 segundos. Locust registra las dos rutas por separado. Al terminar
la prueba, restablece `RATE_LIMIT_ENABLED=true` en dev y confirma el despliegue.

Los resultados del 27/11 están en `docs/qa/reporte-carga-dev.md`. Los 300 equipos
`DEV-LOCUST-*` quedan en dev para repetir la prueba; se retiran con el workflow `dev-reset`.
