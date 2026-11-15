"""Interfaz `pii`: único punto de entrada a los datos personales cifrados.

Los routers y servicios guardan y leen las columnas ``*_ct`` y ``*_bidx`` solo
por medio de estas funciones. Así, cuando SEC-06 (#105) active el cifrado
AES-GCM con el anillo ``DATA_ENC_KEYS``, cambia la implementación de este
módulo y no la de quienes lo usan.

Estado actual (hasta SEC-06): ``proteger`` guarda el texto en UTF-8 sin cifrar,
igual que la semilla de dev y las fixtures de integración. El índice ciego sí
es definitivo: HMAC-SHA256 con ``BLIND_INDEX_KEY`` sobre el valor normalizado.
"""

from app.crypto import compute_blind_index


def proteger(valor: str) -> bytes:
    """Prepara un dato personal para guardarlo en una columna ``*_ct``.

    Args:
        valor: Texto en claro (correo, nombre o código estudiantil).

    Returns:
        Bytes listos para la columna. Hasta SEC-06 son el UTF-8 del texto.
    """
    return valor.encode("utf-8")


def revelar(dato: bytes | None, defecto: str = "") -> str:
    """Recupera el texto de una columna ``*_ct``.

    Args:
        dato: Contenido de la columna, o ``None`` si está vacía.
        defecto: Texto que se devuelve si la columna está vacía.

    Returns:
        El texto en claro, o ``defecto`` si no hay dato.
    """
    if not dato:
        return defecto
    return dato.decode("utf-8", errors="replace")


def indice_ciego(valor: str) -> bytes:
    """Calcula el índice ciego de un dato para buscarlo por igualdad.

    El valor se recorta y se pasa a minúsculas antes del HMAC, de modo que
    ``Ana@U.edu`` y ``ana@u.edu`` dan el mismo índice.

    Args:
        valor: Texto en claro que se quiere indexar.

    Returns:
        HMAC-SHA256 de 32 bytes con ``BLIND_INDEX_KEY``.

    Raises:
        ValueError: Si ``BLIND_INDEX_KEY`` no está configurada.
    """
    return compute_blind_index(valor)
