"""Registros (logging) estructurados en formato JSON.

Todos los módulos usan ``configurar_logger()`` o un logger hijo de
``internet_cafe_backend`` (``obtener_logger("eventos")``), así heredan el
formato JSON. Los datos de un evento van en ``extra={"datos": {...}}`` y nunca
incluyen datos personales, contraseñas, tokens ni credenciales: solo
identificadores internos (UUID), códigos de equipo y nombres de evento.
"""

import json
import logging

NOMBRE_RAIZ = "internet_cafe_backend"


class JSONFormatter(logging.Formatter):
    """Formatea cada registro como un objeto JSON de una línea."""

    def format(self, record: logging.LogRecord) -> str:
        """Convierte el registro en JSON.

        Args:
            record: Registro que emite ``logging``.

        Returns:
            Una línea JSON con hora, nivel, logger, mensaje y, si los hay, los
            datos estructurados de ``extra={"datos": ...}``.
        """
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        datos = getattr(record, "datos", None)
        if isinstance(datos, dict):
            log_record.update({k: v for k, v in datos.items() if k not in log_record})
        return json.dumps(log_record, ensure_ascii=False, default=str)


def configurar_logger() -> logging.Logger:
    """Configura y devuelve el logger raíz de la API, con formato JSON.

    Returns:
        El logger ``internet_cafe_backend``.
    """
    logger = logging.getLogger(NOMBRE_RAIZ)
    logger.setLevel(logging.INFO)

    # Evita duplicar manejadores si la función se llama varias veces
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger


def obtener_logger(nombre: str) -> logging.Logger:
    """Devuelve un logger hijo del raíz, que hereda su salida JSON.

    Args:
        nombre: Sufijo del logger (p. ej. ``"eventos"`` o ``"auth"``).

    Returns:
        El logger ``internet_cafe_backend.<nombre>``.
    """
    configurar_logger()
    return logging.getLogger(f"{NOMBRE_RAIZ}.{nombre}")
