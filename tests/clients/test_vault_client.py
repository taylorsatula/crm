"""Tests for VaultClient - HashiCorp Vault secrets management."""

import os
import pytest

from clients.vault_client import VaultClient, get_database_url, get_valkey_url


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
