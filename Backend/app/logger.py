"""Módulo de registros (logging) estructurados en formato JSON.

Garantiza la trazabilidad de eventos del sistema asegurando la omisión
de datos personales o sensibles en las salidas de consola.
"""

import json
import logging


class JSONFormatter(logging.Formatter):
    """Formateador personalizado para estructurar los logs en formato JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Formatea el registro de log actual en un objeto JSON plano."""
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(log_record)


def configurar_logger() -> logging.Logger:
    """Configura y retorna una instancia de logger con formato JSON estricto.

    Returns:
        logging.Logger: Instancia configurada para la emisión de registros.
    """
    logger = logging.getLogger("internet_cafe_backend")
    logger.setLevel(logging.INFO)

    # Evita duplicar manejadores si la función se llama múltiples veces
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    return logger