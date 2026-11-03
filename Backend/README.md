# Backend · Internet Café API

## Pruebas

```bash
cd Backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # en Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest
```

## Errores (RFC 9457)

Todas las respuestas de error salen como `application/problem+json` con un `code` estable del catálogo (SRS §10.5). Los manejadores están en `app/error_handlers.py` y el catálogo en `app/errors.py`.

Para devolver un error desde un router, lanza un `AppError` con un `ErrorCode`, nunca un `HTTPException`:

```python
from app.errors import AppError, ErrorCode

raise AppError(ErrorCode.CHALLENGE_EXPIRED)
raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"})
```

Para agregar un código nuevo, añádelo a `ErrorCode` y a `CATALOGO` (status, título y detalle). La prueba `tests/unit/test_catalogo_errores.py` falla si falta alguno.

Los 422 solo devuelven `field` y `message` por campo: nunca el valor enviado (`input`).
