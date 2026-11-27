"""Puerto y adaptador HTTP para el correo transaccional de HU-24."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx


@dataclass(frozen=True, repr=False)
class Correo:
    """Mensaje renderizado con destinatario y cuerpos de texto y HTML."""

    destinatario: str
    asunto: str
    texto: str
    html: str


class ErrorEnvio(Exception):
    """Error de entrega con un motivo técnico apto para guardar en el outbox."""

    def __init__(self, motivo: str, *, reintentable: bool = True) -> None:
        """Conserva un código sin datos del mensaje y la política de reintento."""
        super().__init__(motivo)
        self.reintentable = reintentable


class EmailSender(Protocol):
    """Entrega un correo con una clave idempotente y devuelve el id del proveedor."""

    async def enviar(self, correo: Correo, idempotencia: UUID) -> str:
        """Entrega el mensaje al proveedor.

        Args:
            correo: Destinatario, asunto y contenido renderizado.
            idempotencia: UUID de la fila del outbox, estable entre intentos.

        Returns:
            Identificador del mensaje asignado por el proveedor.

        Raises:
            ErrorEnvio: Si el proveedor no confirma la entrega.
        """
        ...


class ResendEmailSender:
    """Envía un correo por la API HTTPS de Resend."""

    def __init__(self, cliente: httpx.AsyncClient, api_key: str, remitente: str) -> None:
        """Recibe el cliente HTTP y la configuración privada del entorno."""
        self._cliente = cliente
        self._api_key = api_key
        self._remitente = remitente

    async def enviar(self, correo: Correo, idempotencia: UUID) -> str:
        """Envía el mensaje a Resend usando el UUID como ``Idempotency-Key``.

        Args:
            correo: Destinatario, asunto y contenido renderizado.
            idempotencia: UUID de la fila del outbox, estable entre intentos.

        Returns:
            Identificador del mensaje devuelto por Resend.

        Raises:
            ErrorEnvio: Si falla el transporte, Resend rechaza el mensaje o la respuesta es inválida.
        """
        try:
            async with asyncio.timeout(5):
                respuesta = await self._cliente.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {self._api_key}", "Idempotency-Key": str(idempotencia)},
                    json={
                        "from": self._remitente,
                        "to": [correo.destinatario],
                        "subject": correo.asunto,
                        "text": correo.texto,
                        "html": correo.html,
                    },
                    follow_redirects=False,
                )
        except (httpx.TransportError, TimeoutError):
            raise ErrorEnvio("transporte") from None

        if not respuesta.is_success:
            codigo = respuesta.status_code
            reintentable = (
                codigo in (408, 429)
                or respuesta.is_server_error
                or (codigo == 409 and _campo(respuesta, "name") == "concurrent_idempotent_requests")
            )
            raise ErrorEnvio(f"http_{codigo}", reintentable=reintentable)

        identificador = _campo(respuesta, "id")
        if not isinstance(identificador, str) or not 0 < len(identificador) <= 100:
            raise ErrorEnvio("respuesta_invalida")
        return identificador


def _campo(respuesta: httpx.Response, nombre: str) -> object:
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return None
    return cuerpo.get(nombre) if isinstance(cuerpo, dict) else None
