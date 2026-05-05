"""
Tests for EmailGatewayClient.

RED phase: Tests verify the client's contract with calling code.
Focus on observable behavior, not implementation details.
"""

import pytest
import responses

from clients.email_client import EmailGatewayClient, EmailGatewayError


class TestEmailGatewayClientInit:
    """Test client initialization - fail-fast on invalid config."""

    def test_init_with_valid_credentials(self):
        """Client initializes with all required credentials."""
        client = EmailGatewayClient(
            gateway_url="https://gateway.example.com/send",
            api_key="test-api-key",
            hmac_secret="test-hmac-secret",
            health_url="https://gateway.example.com/health",
        )
        assert client is not None

    def test_init_rejects_empty_gateway_url(self):
        """Empty gateway_url raises ValueError."""
        with pytest.raises(ValueError, match="gateway_url"):
            EmailGatewayClient(
                gateway_url="",
                api_key="test-api-key",
                hmac_secret="test-hmac-secret",
                health_url="https://gateway.example.com/health",
            )

    def test_init_rejects_empty_api_key(self):
        """Empty api_key raises ValueError."""
        with pytest.raises(ValueError, match="api_key"):
            EmailGatewayClient(
                gateway_url="https://gateway.example.com/send",
                api_key="",
                hmac_secret="test-hmac-secret",
                health_url="https://gateway.example.com/health",
            )

    def test_init_rejects_empty_hmac_secret(self):
        """Empty hmac_secret raises ValueError."""
        with pytest.raises(ValueError, match="hmac_secret"):
            EmailGatewayClient(
                gateway_url="https://gateway.example.com/send",
                api_key="test-api-key",
                hmac_secret="",
                health_url="https://gateway.example.com/health",
            )

    def test_init_rejects_empty_health_url(self):
        """Empty health_url raises ValueError."""
        with pytest.raises(ValueError, match="health_url"):
            EmailGatewayClient(
                gateway_url="https://gateway.example.com/send",
                api_key="test-api-key",
                hmac_secret="test-hmac-secret",
                health_url="",
            )


class TestSendMagicLink:
    """Test send_magic_link - uses responses library for HTTP mocking."""

    GATEWAY_URL = "https://gateway.example.com/send"
    HEALTH_URL = "https://gateway.example.com/health"

    @pytest.fixture
    def client(self):
        """Create client with test credentials."""
        return EmailGatewayClient(
            gateway_url=self.GATEWAY_URL,
            api_key="test-api-key",
            hmac_secret="test-hmac-secret",
            health_url=self.HEALTH_URL,
        )

    @responses.activate
    def test_successful_send_returns_none(self, client):
        """Successful gateway response completes without exception."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            json={"success": True},
            status=200,
        )

        # Should not raise
        result = client.send_magic_link(
            email="user@example.com",
            token="abc123",
            app_url="https://app.example.com",
        )
        assert result is None

    @responses.activate
    def test_gateway_500_raises_error(self, client):
        """Server error from gateway raises EmailGatewayError."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            json={"success": False, "message": "Internal error"},
            status=500,
        )

        with pytest.raises(EmailGatewayError):
            client.send_magic_link(
                email="user@example.com",
                token="abc123",
                app_url="https://app.example.com",
            )

    @responses.activate
    def test_gateway_success_false_raises_error(self, client):
        """Gateway returns 200 but success=false raises EmailGatewayError."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            json={"success": False, "message": "Invalid email"},
            status=200,
        )

        with pytest.raises(EmailGatewayError):
            client.send_magic_link(
                email="invalid",
                token="abc123",
                app_url="https://app.example.com",
            )

    @responses.activate
    def test_connection_failure_raises_error(self, client):
        """Network failure raises EmailGatewayError."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            body=ConnectionError("Network unreachable"),
        )

        with pytest.raises(EmailGatewayError):
            client.send_magic_link(
                email="user@example.com",
                token="abc123",
                app_url="https://app.example.com",
            )

    @responses.activate
    def test_invalid_json_response_raises_error(self, client):
        """Non-JSON response raises EmailGatewayError."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            body="not json",
            status=200,
        )

        with pytest.raises(EmailGatewayError):
            client.send_magic_link(
                email="user@example.com",
                token="abc123",
                app_url="https://app.example.com",
            )


class TestSendEmail:
    """Test generic send_email method."""

    GATEWAY_URL = "https://gateway.example.com/send"
    HEALTH_URL = "https://gateway.example.com/health"

    @pytest.fixture
    def client(self):
        """Create client with test credentials."""
        return EmailGatewayClient(
            gateway_url=self.GATEWAY_URL,
            api_key="test-api-key",
            hmac_secret="test-hmac-secret",
            health_url=self.HEALTH_URL,
        )

    @responses.activate
    def test_successful_send(self, client):
        """Successful send completes without exception."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            json={"success": True},
            status=200,
        )

        result = client.send_email(
            to="user@example.com",
            subject="Test Subject",
            body="Test body",
        )
        assert result is None

    def test_invalid_sender_raises_value_error(self, client):
        """Invalid sender value raises ValueError before any HTTP call."""
        with pytest.raises(ValueError, match="sender must be"):
            client.send_email(
                to="user@example.com",
                subject="Test",
                body="Body",
                sender="invalid",
            )

    @responses.activate
    def test_gateway_error_raises_exception(self, client):
        """Gateway error raises EmailGatewayError."""
        responses.add(
            responses.POST,
            self.GATEWAY_URL,
            json={"success": False},
            status=500,
        )

        with pytest.raises(EmailGatewayError):
            client.send_email(
                to="user@example.com",
                subject="Test",
                body="Body",
            )


class TestHealthCheck:
    """Test gateway health check contract."""

    GATEWAY_URL = "https://gateway.example.com/send"
    HEALTH_URL = "https://gateway.example.com/health"
    API_KEY = "test-api-key"
    HMAC_SECRET = "test-hmac-secret"

    @pytest.fixture
    def client(self):
        return EmailGatewayClient(
            gateway_url=self.GATEWAY_URL,
            api_key=self.API_KEY,
            hmac_secret=self.HMAC_SECRET,
            health_url=self.HEALTH_URL,
        )

    @responses.activate
    def test_health_check_posts_signed_health_payload_to_health_url(self, client):
        responses.add(
            responses.POST,
            self.HEALTH_URL,
            json={"success": True},
            status=200,
        )

        assert client.health_check() is True

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.url == self.HEALTH_URL
        assert request.body == '{"type":"health"}'
        assert request.headers["X-API-Key"] == self.API_KEY
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["X-Signature"] == (
            "9e31f0556716356b3b4d7897dd9b4b156a800704a57f9f97489d0aedde3620e3"
        )

    @responses.activate
    def test_health_check_does_not_post_to_send_gateway_url(self, client):
        responses.add(
            responses.POST,
            self.HEALTH_URL,
            json={"success": True},
            status=200,
        )

        client.health_check()

        assert responses.calls[0].request.url == self.HEALTH_URL

    @responses.activate
    def test_health_check_raises_on_non_2xx_response(self, client):
        responses.add(
            responses.POST,
            self.HEALTH_URL,
            json={"success": False, "message": "unavailable"},
            status=503,
        )

        with pytest.raises(EmailGatewayError, match="unavailable"):
            client.health_check()

    @responses.activate
    def test_health_check_raises_when_success_false(self, client):
        responses.add(
            responses.POST,
            self.HEALTH_URL,
            json={"success": False, "message": "bad signature"},
            status=200,
        )

        with pytest.raises(EmailGatewayError, match="bad signature"):
            client.health_check()
