"""
Valkey (Redis-compatible) client for sessions and rate limiting.

Simple wrapper around redis-py. Connection URL from Vault.
Fail-fast: raises on connection failure, never returns fallback values.
"""

import json
import logging
from typing import Any

import redis

logger = logging.getLogger(__name__)


class ValkeyClient:
    """
    Redis-compatible client for Valkey.

    Usage:
        client = ValkeyClient("redis://localhost:6379/0")
        client.set("key", "value", expire_seconds=300)
        value = client.get("key")  # Returns None if missing
    """

    def __init__(self, url: str):
        """
        Initialize Valkey connection.

        Args:
            url: Redis-compatible connection URL (e.g., redis://localhost:6379/0)

        Raises:
            redis.ConnectionError: If connection fails
        """
        self._client = redis.from_url(url, decode_responses=True)
        # Verify connectivity immediately (fail-fast)
        self._client.ping()
        logger.info("ValkeyClient connected")

    def ping(self) -> bool:
        """
        Health check.

        Returns True if Valkey responds.
        Raises redis.ConnectionError if unreachable.
        """
        self._client.ping()
        return True

    def get(self, key: str) -> str | None:
        """
        Get value by key.

        Returns None if key doesn't exist (not an error).
        Raises on connection failure.
        """
        return self._client.get(key)

    def set(self, key: str, value: str, expire_seconds: int | None = None) -> None:
        """
        Set key to value, optionally with expiration.

        Args:
            key: Key to set
            value: Value to store
            expire_seconds: TTL in seconds (None for no expiration)
        """
        if expire_seconds is not None:
            self._client.setex(key, expire_seconds, value)
        else:
            self._client.set(key, value)

    def delete(self, key: str) -> bool:
        """
        Delete key.

        Returns True if key existed and was deleted, False if key didn't exist.
        """
        return self._client.delete(key) > 0

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return self._client.exists(key) > 0

    def ttl(self, key: str) -> int:
        """
        Get remaining TTL in seconds.

        Returns:
            -2 if key doesn't exist
            -1 if key has no expiration
            Positive int: remaining seconds
        """
        return self._client.ttl(key)

    def incr(self, key: str) -> int:
        """
        Increment key by 1.

        Creates key with value 1 if it doesn't exist.
        Returns the new value.
        """
        return self._client.incr(key)

    def set_json(self, key: str, value: dict | list, expire_seconds: int | None = None) -> None:
        """
        Set key to JSON-serialized value.

        Args:
            key: Key to set
            value: Dict or list to serialize
            expire_seconds: TTL in seconds (None for no expiration)
        """
        json_str = json.dumps(value)
        self.set(key, json_str, expire_seconds)

    def get_json(self, key: str) -> dict | list | None:
        """
        Get and deserialize JSON value.

        Returns None if key doesn't exist.
        Raises ValueError if value is not valid JSON.
        """
        value = self.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in key '{key}': {e}")

    def close(self) -> None:
        """Close the connection."""
        self._client.close()
        logger.info("ValkeyClient closed")
