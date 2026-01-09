"""
Email gateway client for sending emails via HTTP gateway.

Uses HMAC-SHA256 signature for request authentication.
Same pattern as botwithmemory project.
"""

import hashlib
import hmac
import json
import logging

import requests

logger = logging.getLogger(__name__)


class EmailGatewayError(Exception):
    """Raised when email gateway request fails."""


class EmailGatewayClient:
    """Send emails via HTTP gateway with HMAC signature verification."""

    def __init__(self, gateway_url: str, api_key: str, hmac_secret: str):
        """
        Initialize with gateway credentials.

        Args:
            gateway_url: Full URL to the email gateway endpoint
            api_key: API key for X-API-Key header
            hmac_secret: Secret for HMAC-SHA256 signature

        Raises:
            ValueError: If any credential is empty
        """
        if not gateway_url:
            raise ValueError("gateway_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not hmac_secret:
            raise ValueError("hmac_secret is required")

        self.gateway_url = gateway_url
        self.api_key = api_key
        self.hmac_secret = hmac_secret

    def _sign_and_send(self, payload: dict) -> None:
        """
        Sign payload with HMAC and send to gateway.

        Args:
            payload: Dict to send as JSON

        Raises:
            EmailGatewayError: On any failure
        """
        payload_json = json.dumps(payload, separators=(",", ":"))

        signature = hmac.new(
            self.hmac_secret.encode("utf-8"),
            payload_json.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Signature": signature,
        }

        try:
            response = requests.post(
                self.gateway_url,
                data=payload_json,
                headers=headers,
                timeout=10,
            )
        except (requests.exceptions.RequestException, ConnectionError) as e:
            logger.error(f"Email gateway connection failed: {e}")
            raise EmailGatewayError(f"Connection failed: {e}")

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Email gateway returned invalid JSON: {response.text}")
            raise EmailGatewayError("Invalid response from gateway")

        if response.status_code != 200 or not response_data.get("success"):
            error_msg = response_data.get("message", "Unknown error")
            logger.error(f"Email gateway error: {error_msg}")
            raise EmailGatewayError(f"Gateway error: {error_msg}")

    def send_magic_link(self, email: str, token: str, app_url: str) -> None:
        """
        Send magic link email via gateway.

        Args:
            email: Recipient email address
            token: Magic link token
            app_url: Application base URL for constructing the link

        Raises:
            EmailGatewayError: On any failure
        """
        payload = {
            "email": email,
            "token": token,
            "app_url": app_url,
        }
        self._sign_and_send(payload)
        logger.info(f"Magic link email sent to {email}")

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        sender: str = "system",
    ) -> None:
        """
        Send an arbitrary email via gateway.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain text email body
            sender: Sender identity - "auth" or "system" (default: "system")

        Raises:
            ValueError: If sender is invalid
            EmailGatewayError: On gateway failure
        """
        if sender not in ("auth", "system"):
            raise ValueError(f"sender must be 'auth' or 'system', got '{sender}'")

        payload = {
            "type": "custom",
            "email": to,
            "subject": subject,
            "body": body,
            "sender": sender,
        }
        self._sign_and_send(payload)
        logger.info(f"Email sent to {to}: {subject}")
