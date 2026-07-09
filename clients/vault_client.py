"""
HashiCorp Vault client for CRM secret management.

Uses AppRole authentication. Fails fast on missing configuration.
All paths scoped to 'crm/' prefix - no escape to other secrets.
"""

import os
import logging
from typing import Dict

import hvac
from hvac.exceptions import InvalidPath, Unauthorized, Forbidden

logger = logging.getLogger(__name__)

# Project scope - all secrets under this path
_SECRET_PREFIX = "crm"

# Singleton instance and cache
_vault_client_instance: "VaultClient | None" = None
_secret_cache: Dict[str, str] = {}


def _ensure_vault_client() -> "VaultClient":
    global _vault_client_instance
    if _vault_client_instance is None:
        _vault_client_instance = VaultClient()
    return _vault_client_instance


class VaultError(Exception):
    """Vault operation failed. Fatal - application cannot function without secrets."""


class VaultClient:
    """Vault client with AppRole auth, env-based config, and fail-fast behavior."""

    def __init__(
        self,
        vault_addr: str | None = None,
        vault_namespace: str | None = None,
    ):
        """Initialize with environment variables. Fails fast on missing config."""
        self.vault_addr = vault_addr or os.getenv("VAULT_ADDR")
        self.vault_namespace = vault_namespace or os.getenv("VAULT_NAMESPACE")
        self.vault_role_id = os.getenv("VAULT_ROLE_ID")
        self.vault_secret_id = os.getenv("VAULT_SECRET_ID")

        if not self.vault_addr:
            raise ValueError("VAULT_ADDR environment variable is required")

        if not self.vault_role_id or not self.vault_secret_id:
            raise ValueError(
                "VAULT_ROLE_ID and VAULT_SECRET_ID environment variables are required"
            )

        client_kwargs = {"url": self.vault_addr}
        if self.vault_namespace:
            client_kwargs["namespace"] = self.vault_namespace

        self.client = hvac.Client(**client_kwargs)
        self._authenticate_approle()

        if not self.client.is_authenticated():
            raise PermissionError("Vault authentication failed")

        logger.info(f"Vault client initialized: {self.vault_addr}")

    def _authenticate_approle(self) -> None:
        """Authenticate using AppRole credentials."""
        try:
            auth_response = self.client.auth.approle.login(
                role_id=self.vault_role_id,
                secret_id=self.vault_secret_id,
            )
            self.client.token = auth_response["auth"]["client_token"]
            logger.info("AppRole authentication successful")
        except Exception as e:
            logger.error(f"AppRole authentication failed: {e}")
            raise PermissionError(f"AppRole authentication failed: {e}")

    def get_secret(self, path: str, field: str) -> str:
        """
        Retrieve single field from KV v2 secret.

        Path is automatically scoped to 'crm/' prefix.
        Caller passes 'database', we access 'crm/database'.

        Args:
            path: Secret path relative to crm/ (e.g., 'database', 'internal')
            field: Field name within secret (e.g., 'url')

        Returns:
            Field value as string.

        Raises:
            PermissionError: Path not accessible or doesn't exist.
            KeyError: Field not found in secret.
        """
        full_path = f"{_SECRET_PREFIX}/{path}"

        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=full_path, raise_on_deleted_version=True
            )
            secret_data = response["data"]["data"]

            if field not in secret_data:
                available = list(secret_data.keys())
                raise KeyError(
                    f"Field '{field}' not found in secret '{full_path}'. "
                    f"Available: {', '.join(available)}"
                )

            return secret_data[field]

        except InvalidPath:
            logger.error(f"Secret path not found: {full_path}")
            raise PermissionError(f"Secret path '{full_path}' not found in Vault")

        except (Unauthorized, Forbidden) as e:
            logger.error(f"Access denied to secret {full_path}: {e}")
            raise PermissionError(f"Access denied to secret '{full_path}': {e}")

    def health_check(self) -> bool:
        """Return True when Vault is initialized and unsealed."""
        try:
            status = self.client.sys.read_health_status(
                method="GET",
                standby_ok=True,
            )
        except Exception as e:
            logger.error(f"Vault health check failed: {e}")
            raise VaultError(f"Vault health check failed: {e}")

        if not status.get("initialized", False):
            raise VaultError("Vault is not initialized")
        if status.get("sealed", True):
            raise VaultError("Vault is sealed")

        return True

    def get_llm_config(self) -> Dict[str, str]:
        """Get LLM API key and optional OpenAI-compatible base URL."""
        return _get_llm_config(self)


# Convenience functions


def _get_llm_config(client: VaultClient) -> Dict[str, str]:
    """Build LLM config from an existing Vault client."""
    result = {}

    api_key_cache_key = "crm/llm/api_key"
    if api_key_cache_key in _secret_cache:
        result["api_key"] = _secret_cache[api_key_cache_key]
    else:
        value = client.get_secret("llm", "api_key")
        _secret_cache[api_key_cache_key] = value
        result["api_key"] = value

    base_url_cache_key = "crm/llm/base_url"
    if base_url_cache_key in _secret_cache:
        result["base_url"] = _secret_cache[base_url_cache_key]
    else:
        try:
            value = client.get_secret("llm", "base_url")
        except KeyError:
            value = None

        if value:
            _secret_cache[base_url_cache_key] = value
            result["base_url"] = value

    model_cache_key = "crm/llm/model"
    if model_cache_key in _secret_cache:
        result["model"] = _secret_cache[model_cache_key]
    else:
        try:
            value = client.get_secret("llm", "model")
        except KeyError:
            value = None

        if value:
            _secret_cache[model_cache_key] = value
            result["model"] = value

    return result


def get_database_url() -> str:
    """Get PostgreSQL connection URL from Vault."""
    cache_key = "crm/database/url"

    if cache_key in _secret_cache:
        return _secret_cache[cache_key]

    client = _ensure_vault_client()
    value = client.get_secret("database", "url")
    _secret_cache[cache_key] = value
    return value


def get_email_config() -> Dict[str, str]:
    """Get email gateway configuration from Vault.

    Returns:
        Dict with keys: gateway_url, api_key, hmac_secret, health_url
    """
    client = _ensure_vault_client()

    fields = ["gateway_url", "api_key", "hmac_secret", "health_url"]
    result = {}

    for field in fields:
        cache_key = f"crm/email/{field}"
        if cache_key in _secret_cache:
            result[field] = _secret_cache[cache_key]
        else:
            value = client.get_secret("email", field)
            _secret_cache[cache_key] = value
            result[field] = value

    return result


def get_llm_config() -> Dict[str, str]:
    """Get LLM API key and optional OpenAI-compatible base URL from Vault.

    Returns:
        Dict with keys: api_key and optionally base_url
    """
    return _get_llm_config(_ensure_vault_client())
