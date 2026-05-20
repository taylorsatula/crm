"""Tests for VaultClient - HashiCorp Vault secrets management."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from hvac.exceptions import Forbidden, InvalidPath, Unauthorized

import clients.vault_client as vault_module
from clients.vault_client import (
    VaultClient,
    VaultError,
    get_database_url,
    get_email_config,
    get_llm_config,
    get_valkey_url,
)


DEFAULT_SECRETS = {
    "crm/database": {
        "url": "postgresql://app:pass@localhost:5432/crm",
        "admin_url": "postgresql://admin:pass@localhost:5432/crm",
    },
    "crm/valkey": {"url": "redis://localhost:6379/0"},
    "crm/email": {
        "gateway_url": "https://email.example.com/send",
        "api_key": "email-key",
        "hmac_secret": "email-secret",
        "health_url": "https://email.example.com/health",
    },
    "crm/llm": {
        "api_key": "llm-key",
        "base_url": "https://llm.example.com/v1",
    },
}


class FakeAppRole:
    def __init__(self, owner):
        self.owner = owner

    def login(self, role_id, secret_id):
        if self.owner.login_error:
            raise self.owner.login_error
        if role_id == "invalid-role-id" or secret_id == "invalid-secret-id":
            raise PermissionError("invalid credentials")

        self.owner.authenticated = True
        return {"auth": {"client_token": "vault-token"}}


class FakeAuth:
    def __init__(self, owner):
        self.approle = FakeAppRole(owner)


class FakeKVV2:
    def __init__(self, owner):
        self.owner = owner

    def read_secret_version(self, path, raise_on_deleted_version=True):
        if self.owner.read_error:
            raise self.owner.read_error
        if path not in self.owner.secret_data:
            raise InvalidPath
        return {"data": {"data": self.owner.secret_data[path]}}


class FakeKV:
    def __init__(self, owner):
        self.v2 = FakeKVV2(owner)


class FakeSecrets:
    def __init__(self, owner):
        self.kv = FakeKV(owner)


class FakeHvacClient:
    def __init__(self, *, url, namespace=None, secrets=None):
        self.url = url
        self.namespace = namespace
        self.secret_data = secrets if secrets is not None else deepcopy(DEFAULT_SECRETS)
        self.authenticated = False
        self.login_error = None
        self.read_error = None
        self.token = None
        self.auth = FakeAuth(self)
        self.secrets = FakeSecrets(self)
        self.sys = FakeVaultSys({"initialized": True, "sealed": False})

    def is_authenticated(self):
        return self.authenticated


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


@pytest.fixture(autouse=True)
def reset_vault_module():
    vault_module._vault_client_instance = None
    vault_module._secret_cache.clear()
    yield
    vault_module._vault_client_instance = None
    vault_module._secret_cache.clear()


@pytest.fixture
def vault_env(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.example.com")
    monkeypatch.setenv("VAULT_NAMESPACE", "admin")
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")


@pytest.fixture
def fake_hvac(monkeypatch, vault_env):
    secrets = deepcopy(DEFAULT_SECRETS)
    created = []

    def client_factory(**kwargs):
        client = FakeHvacClient(**kwargs, secrets=secrets)
        created.append(client)
        return client

    monkeypatch.setattr(vault_module.hvac, "Client", client_factory)
    return SimpleNamespace(created=created, secrets=secrets)


class TestVaultClientInit:
    """Initialization and authentication."""

    def test_missing_vault_addr_raises(self, monkeypatch):
        """VAULT_ADDR required."""
        monkeypatch.delenv("VAULT_ADDR", raising=False)

        with pytest.raises(ValueError, match="VAULT_ADDR"):
            VaultClient()

    def test_missing_approle_credentials_raises(self, monkeypatch):
        """VAULT_ROLE_ID and VAULT_SECRET_ID required."""
        monkeypatch.setenv("VAULT_ADDR", "http://vault.example.com")
        monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
        monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

        with pytest.raises(ValueError, match="VAULT_ROLE_ID"):
            VaultClient()

    def test_invalid_approle_raises_permission_error(self, fake_hvac, monkeypatch):
        """Invalid AppRole credentials fail authentication."""
        monkeypatch.setenv("VAULT_ROLE_ID", "invalid-role-id")
        monkeypatch.setenv("VAULT_SECRET_ID", "invalid-secret-id")

        with pytest.raises(PermissionError, match="authentication"):
            VaultClient()

    def test_valid_approle_authenticates(self, fake_hvac):
        """Valid AppRole credentials authenticate successfully."""
        client = VaultClient()

        assert client.client.is_authenticated()
        assert client.client.url == "http://vault.example.com"
        assert client.client.namespace == "admin"


class TestGetSecret:
    """Secret retrieval - paths automatically scoped to crm/."""

    def test_returns_field_value(self, fake_hvac):
        """get_secret returns string value for field."""
        client = VaultClient()

        url = client.get_secret("database", "url")

        assert url == "postgresql://app:pass@localhost:5432/crm"

    def test_missing_path_raises(self, fake_hvac):
        """Non-existent path raises PermissionError."""
        client = VaultClient()

        with pytest.raises(PermissionError):
            client.get_secret("nonexistent", "field")

    def test_missing_field_raises_keyerror(self, fake_hvac):
        """Missing field in existing secret raises KeyError."""
        client = VaultClient()

        with pytest.raises(KeyError, match="not found"):
            client.get_secret("database", "nonexistent_field")

    def test_unauthorized_read_raises_permission_error(self, fake_hvac):
        """Vault authorization failures are mapped to PermissionError."""
        client = VaultClient()
        client.client.secrets.kv.v2.owner.read_error = Unauthorized("denied")

        with pytest.raises(PermissionError, match="Access denied"):
            client.get_secret("database", "url")

    def test_forbidden_read_raises_permission_error(self, fake_hvac):
        """Vault forbidden failures are mapped to PermissionError."""
        client = VaultClient()
        client.client.secrets.kv.v2.owner.read_error = Forbidden("denied")

        with pytest.raises(PermissionError, match="Access denied"):
            client.get_secret("database", "url")


class TestConvenienceFunctions:
    """Module-level convenience functions."""

    def test_get_database_url_returns_postgresql(self, fake_hvac):
        """get_database_url returns PostgreSQL connection string."""
        url = get_database_url()

        assert url.startswith("postgresql://")

    def test_get_valkey_url_returns_redis(self, fake_hvac):
        """get_valkey_url returns Redis connection string."""
        url = get_valkey_url()

        assert url.startswith("redis://")

    def test_get_email_config_requires_health_url(self, fake_hvac):
        """Email config includes all fields required for runtime and health checks."""
        config = get_email_config()

        assert set(config) == {"gateway_url", "api_key", "hmac_secret", "health_url"}
        assert config["health_url"].startswith(("http://", "https://"))

    def test_get_llm_config_returns_api_key_and_optional_base_url(self, fake_hvac):
        """LLM config includes API key and compatible provider URL when present."""
        config = get_llm_config()

        assert config == {
            "api_key": "llm-key",
            "base_url": "https://llm.example.com/v1",
        }

    def test_get_llm_config_allows_missing_base_url(self, fake_hvac):
        """LLM base_url is optional for the default OpenAI endpoint."""
        del fake_hvac.secrets["crm/llm"]["base_url"]

        assert get_llm_config() == {"api_key": "llm-key"}

    def test_convenience_functions_cache_secret_values(self, fake_hvac):
        """Convenience functions cache values after the first Vault read."""
        assert get_database_url() == "postgresql://app:pass@localhost:5432/crm"
        fake_hvac.secrets["crm/database"]["url"] = "postgresql://changed"

        assert get_database_url() == "postgresql://app:pass@localhost:5432/crm"


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
