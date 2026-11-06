# Internet Café — Backend (contrato v0.2)

FastAPI + SQLAlchemy async + PostgreSQL (Neon). Errores RFC 9457 (`application/problem+json`) vía `app/error_handlers.py`:
sin `input`, credenciales, tokens ni trazas en las respuestas.

- Configuración: copia `.env.example` → `.env` (valores ficticios; nunca secretos reales).
- Base de datos y roles: ver `db/README.md`.
- Contrato: `openapi.yaml` / `Contrato.md` (v0.2.0).
- Pruebas: `python -m pytest`.

## Concurrencia (BE-05 / BE-07b)
Orden de bloqueos fijo: fila del equipo `FOR UPDATE` → retos → sesiones. Las cancelaciones de retos son `UPDATE` masivos con
`WHERE status = 'pending'`, así un reto `approved` nunca se pisa.
