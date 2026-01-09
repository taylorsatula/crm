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
            path: Secret path relative to crm/ (e.g., 'database', 'valkey')
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


# Convenience functions


def get_database_url() -> str:
    """Get PostgreSQL connection URL from Vault."""
    cache_key = "crm/database/url"

    if cache_key in _secret_cache:
        return _secret_cache[cache_key]

    client = _ensure_vault_client()
    value = client.get_secret("database", "url")
    _secret_cache[cache_key] = value
    return value


def get_valkey_url() -> str:
    """Get Valkey (Redis) connection URL from Vault."""
    cache_key = "crm/valkey/url"

    if cache_key in _secret_cache:
        return _secret_cache[cache_key]

    client = _ensure_vault_client()
    value = client.get_secret("valkey", "url")
    _secret_cache[cache_key] = value
    return value


def get_email_config() -> Dict[str, str]:
    """Get email gateway configuration from Vault.

    Returns:
        Dict with keys: gateway_url, api_key, hmac_secret
    """
    client = _ensure_vault_client()

    fields = ["gateway_url", "api_key", "hmac_secret"]
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
    """Get LLM API configuration from Vault."""
    client = _ensure_vault_client()

    fields = ["api_key", "base_url", "model_name"]
    result = {}

    for field in fields:
        cache_key = f"crm/llm/{field}"
        if cache_key in _secret_cache:
            result[field] = _secret_cache[cache_key]
        else:
            value = client.get_secret("llm", field)
            _secret_cache[cache_key] = value
            result[field] = value

    return result


def get_stripe_config() -> Dict[str, str]:
    """Get Stripe configuration from Vault."""
    client = _ensure_vault_client()

    fields = ["secret_key", "webhook_secret", "publishable_key"]
    result = {}

    for field in fields:
        cache_key = f"crm/stripe/{field}"
        if cache_key in _secret_cache:
            result[field] = _secret_cache[cache_key]
        else:
            value = client.get_secret("stripe", field)
            _secret_cache[cache_key] = value
            result[field] = value

    return result
