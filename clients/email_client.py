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

    def __init__(
        self,
        gateway_url: str,
        api_key: str,
        hmac_secret: str,
        health_url: str,
    ):
        """
        Initialize with gateway credentials.

        Args:
            gateway_url: Full URL to the email gateway endpoint
            api_key: API key for X-API-Key header
            hmac_secret: Secret for HMAC-SHA256 signature
            health_url: Full URL to the email gateway health endpoint

        Raises:
            ValueError: If any credential is empty
        """
        if not gateway_url:
            raise ValueError("gateway_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not hmac_secret:
            raise ValueError("hmac_secret is required")
        if not health_url:
            raise ValueError("health_url is required")

        self.gateway_url = gateway_url
        self.api_key = api_key
        self.hmac_secret = hmac_secret
        self.health_url = health_url

    def _signed_headers(self, payload_json: str) -> dict[str, str]:
        """Build authenticated headers for a compact JSON payload."""
        signature = hmac.new(
            self.hmac_secret.encode("utf-8"),
            payload_json.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Signature": signature,
        }

    def _post_signed_payload(
        self,
        url: str,
        payload: dict,
        timeout: int,
    ) -> dict:
        """Sign and POST a payload, returning decoded JSON on success."""
        payload_json = json.dumps(payload, separators=(",", ":"))
        headers = self._signed_headers(payload_json)

        try:
            response = requests.post(
                url,
                data=payload_json,
                headers=headers,
                timeout=timeout,
            )
        except (requests.exceptions.RequestException, ConnectionError) as e:
            logger.error(f"Email gateway connection failed: {e}")
            raise EmailGatewayError(f"Connection failed: {e}")

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Email gateway returned invalid JSON: {response.text}")
            raise EmailGatewayError("Invalid response from gateway")

        if not 200 <= response.status_code < 300 or not response_data.get("success"):
            error_msg = response_data.get("message", "Unknown error")
            logger.error(f"Email gateway error: {error_msg}")
            raise EmailGatewayError(f"Gateway error: {error_msg}")

        return response_data

    def _sign_and_send(self, payload: dict) -> None:
        """
        Sign payload with HMAC and send to gateway.

        Args:
            payload: Dict to send as JSON

        Raises:
            EmailGatewayError: On any failure
        """
        self._post_signed_payload(self.gateway_url, payload, timeout=10)

    def health_check(self) -> bool:
        """Check gateway availability without sending an email."""
        self._post_signed_payload(
            self.health_url,
            {"type": "health"},
            timeout=3,
        )
        return True

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        """
        Send an arbitrary email via gateway.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain text email body
        Raises:
            EmailGatewayError: On gateway failure
        """
        payload = {
            "type": "custom",
            "email": to,
            "subject": subject,
            "body": body,
            "sender": "system",
        }
        self._sign_and_send(payload)
        logger.info(f"Email sent to {to}: {subject}")
