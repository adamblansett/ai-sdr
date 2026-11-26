import asyncio
import smtplib
import uuid
from email.message import EmailMessage

import httpx
from fastapi import Request
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.resilience import async_retry_with_backoff


class DeliveryResult(BaseModel):
    """Result returned by pluggable outbound email/channel delivery providers."""

    provider: str
    message_id: str
    status: str
    detail: str = ""


class EmailDeliveryService:
    """Pluggable outbound email dispatcher (mock, SMTP, Resend, SendGrid)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_smtp_sync(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
    ) -> str:
        if not self.settings.smtp_host.strip():
            raise RuntimeError("SMTP_HOST is not configured.")
        msg = EmailMessage()
        msg["From"] = self.settings.email_from_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        msg_id = f"smtp-{uuid.uuid4().hex[:12]}"
        msg["Message-ID"] = f"<{msg_id}@ai-sdr.local>"

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15.0) as server:
            if self.settings.smtp_use_tls:
                server.starttls()
            if self.settings.smtp_username.strip():
                server.login(self.settings.smtp_username, self.settings.smtp_password)
            server.send_message(msg)
        return msg_id

    async def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
    ) -> DeliveryResult:
        """Dispatch an approved outbound email via configured provider."""
        provider = self.settings.email_provider

        if provider == "mock":
            return DeliveryResult(
                provider="mock",
                message_id=f"msg-{uuid.uuid4().hex[:12]}",
                status="sent",
                detail="Dispatched via deterministic offline mock provider.",
            )

        if provider == "smtp":
            msg_id = await asyncio.to_thread(
                self._send_smtp_sync,
                to_email=to_email,
                subject=subject,
                body=body,
            )
            return DeliveryResult(provider="smtp", message_id=msg_id, status="sent")

        if provider == "resend":
            api_key = self.settings.resend_api_key.strip()
            if not api_key:
                raise RuntimeError("RESEND_API_KEY is not configured.")

            async def _call_resend() -> str:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "from": self.settings.email_from_address,
                            "to": [to_email],
                            "subject": subject,
                            "text": body,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    return str(data.get("id") or f"resend-{uuid.uuid4().hex[:10]}")

            msg_id = await async_retry_with_backoff(_call_resend, max_attempts=2)
            return DeliveryResult(provider="resend", message_id=msg_id, status="sent")

        if provider == "sendgrid":
            api_key = self.settings.sendgrid_api_key.strip()
            if not api_key:
                raise RuntimeError("SENDGRID_API_KEY is not configured.")

            async def _call_sendgrid() -> str:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        "https://api.sendgrid.com/v3/mail/send",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "personalizations": [{"to": [{"email": to_email}]}],
                            "from": {"email": self.settings.email_from_address},
                            "subject": subject,
                            "content": [{"type": "text/plain", "value": body}],
                        },
                    )
                    response.raise_for_status()
                    return response.headers.get(
                        "x-message-id", f"sg-{uuid.uuid4().hex[:10]}"
                    )

            msg_id = await async_retry_with_backoff(_call_sendgrid, max_attempts=2)
            return DeliveryResult(provider="sendgrid", message_id=msg_id, status="sent")

        raise RuntimeError(f"Unsupported email provider: {provider}")


def get_email_delivery_service(request: Request) -> EmailDeliveryService:
    """FastAPI dependency returning the app-scoped EmailDeliveryService."""
    service = getattr(request.app.state, "email_delivery", None)
    if isinstance(service, EmailDeliveryService):
        return service
    return EmailDeliveryService(get_settings())
