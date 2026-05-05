"""Tests for VaultClient - HashiCorp Vault secrets management."""

import os
import pytest

from clients.vault_client import (
    VaultClient,
    VaultError,
    get_database_url,
    get_email_config,
    get_llm_config,
    get_valkey_url,
)


class FakeVaultSys:
    def __init__(self, response=None, error=None):
        self.response = response or {"initialized": True, "sealed": False}
        self.error = error
        self.calls = 0

    def read_health_status(self, method="GET", standby_ok=True):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FakeVaultHvacClient:
    def __init__(self, sys):
        self.sys = sys


class TestVaultClientInit:
    """Initialization and authentication."""

    def test_missing_vault_addr_raises(self):
        """VAULT_ADDR required."""
        original = os.environ.pop("VAULT_ADDR", None)
        try:
            with pytest.raises(ValueError, match="VAULT_ADDR"):
                VaultClient()
        finally:
            if original:
                os.environ["VAULT_ADDR"] = original

    def test_missing_approle_credentials_raises(self):
        """VAULT_ROLE_ID and VAULT_SECRET_ID required."""
        original_role = os.environ.pop("VAULT_ROLE_ID", None)
        original_secret = os.environ.pop("VAULT_SECRET_ID", None)
        try:
            with pytest.raises(ValueError, match="VAULT_ROLE_ID"):
                VaultClient()
        finally:
            if original_role:
                os.environ["VAULT_ROLE_ID"] = original_role
            if original_secret:
                os.environ["VAULT_SECRET_ID"] = original_secret

    def test_invalid_approle_raises_permission_error(self):
        """Invalid AppRole credentials fail authentication."""
        original_role = os.environ.get("VAULT_ROLE_ID")
        original_secret = os.environ.get("VAULT_SECRET_ID")
        try:
            os.environ["VAULT_ROLE_ID"] = "invalid-role-id"
            os.environ["VAULT_SECRET_ID"] = "invalid-secret-id"
            with pytest.raises(PermissionError, match="authentication"):
                VaultClient()
        finally:
            if original_role:
                os.environ["VAULT_ROLE_ID"] = original_role
            if original_secret:
                os.environ["VAULT_SECRET_ID"] = original_secret

    def test_valid_approle_authenticates(self):
        """Valid AppRole credentials authenticate successfully."""
        client = VaultClient()
        assert client.client.is_authenticated()


class TestGetSecret:
    """Secret retrieval - paths automatically scoped to crm/."""

    def test_returns_field_value(self):
        """get_secret returns string value for field."""
        client = VaultClient()
        # Pass "database", internally accesses "crm/database"
        url = client.get_secret("database", "url")
        assert isinstance(url, str)
        assert len(url) > 0

    def test_missing_path_raises(self):
        """Non-existent path raises PermissionError."""
        client = VaultClient()
        with pytest.raises(PermissionError):
            client.get_secret("nonexistent", "field")

    def test_missing_field_raises_keyerror(self):
        """Missing field in existing secret raises KeyError."""
        client = VaultClient()
        with pytest.raises(KeyError, match="not found"):
            client.get_secret("database", "nonexistent_field")


class TestConvenienceFunctions:
    """Module-level convenience functions."""

    def test_get_database_url_returns_postgresql(self):
        """get_database_url returns PostgreSQL connection string."""
        url = get_database_url()
        assert url.startswith("postgresql://")

    def test_get_valkey_url_returns_redis(self):
        """get_valkey_url returns Redis connection string."""
        url = get_valkey_url()
        assert url.startswith("redis://")

    def test_get_email_config_requires_health_url(self):
        """Email config includes all fields required for runtime and health checks."""
        config = get_email_config()
        assert set(config) == {"gateway_url", "api_key", "hmac_secret", "health_url"}
        assert config["health_url"].startswith(("http://", "https://"))

    def test_get_llm_config_requires_health_url(self):
        """LLM config includes API and health endpoint credentials."""
        config = get_llm_config()
        assert set(config) == {"api_key", "health_url"}
        assert config["health_url"].startswith(("http://", "https://"))


class TestVaultHealthCheck:
    """Vault runtime health check."""

    def test_health_check_returns_true_when_vault_is_initialized_and_unsealed(self):
        sys = FakeVaultSys({"initialized": True, "sealed": False})
        client = VaultClient.__new__(VaultClient)
        client.client = FakeVaultHvacClient(sys)

        assert client.health_check() is True
        assert sys.calls == 1

    def test_health_check_raises_vault_error_when_vault_reports_sealed(self):
        client = VaultClient.__new__(VaultClient)
        client.client = FakeVaultHvacClient(
            FakeVaultSys({"initialized": True, "sealed": True})
        )

        with pytest.raises(VaultError, match="sealed"):
            client.health_check()

    def test_health_check_raises_vault_error_on_hvac_failure(self):
        client = VaultClient.__new__(VaultClient)
        client.client = FakeVaultHvacClient(FakeVaultSys(error=RuntimeError("boom")))

        with pytest.raises(VaultError, match="boom"):
            client.health_check()
