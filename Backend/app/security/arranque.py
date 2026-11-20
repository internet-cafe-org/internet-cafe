"""Comprobaciones de seguridad al arrancar la API (HU-07, BE-02).

La API no debe arrancar sin sus llaves: sin ellas el login falla en la primera
petición y el registro no puede calcular los índices ciegos. Estas
comprobaciones se ejecutan en el ``lifespan`` de ``app.main``; las pruebas que
crean el cliente sin ``lifespan`` ponen sus propias llaves con ``monkeypatch``.
"""

from app.config import settings
from app.jwt import create_access_token, verify_access_token


class LlavesInvalidas(RuntimeError):
    """Falta una llave obligatoria o no sirve."""


def verificar_llaves() -> None:
    """Comprueba que las llaves obligatorias existan y funcionen juntas.

    Firma un access token con ``JWT_PRIVATE_KEY`` y lo verifica con
    ``JWT_PUBLIC_KEY``, con las mismas funciones que usa la API; así detecta
    llaves ausentes, mal formadas, de otro algoritmo o que no forman un par.
    También exige ``BLIND_INDEX_KEY``. Los mensajes nombran la variable, nunca
    su contenido.

    Raises:
        LlavesInvalidas: Si falta alguna llave o el par JWT no es válido.
    """
    faltantes = [
        nombre
        for nombre, valor in (
            ("JWT_PRIVATE_KEY", settings.jwt_private_key),
            ("JWT_PUBLIC_KEY", settings.jwt_public_key),
            ("BLIND_INDEX_KEY", settings.blind_index_key),
        )
        if not valor
    ]
    if faltantes:
        raise LlavesInvalidas(
            "Faltan llaves obligatorias: " + ", ".join(faltantes)
            + ". Genéralas con tools/generate_keys.py."
        )

    try:
        token = create_access_token(subject="verificacion-de-arranque", role="student")
        verify_access_token(token)
    except Exception as exc:
        raise LlavesInvalidas(
            "JWT_PRIVATE_KEY y JWT_PUBLIC_KEY no forman un par ES256 válido "
            f"({type(exc).__name__})."
        ) from None
