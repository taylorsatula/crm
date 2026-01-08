"""Tests for ValkeyClient - Redis-compatible session and cache store."""

import pytest
import time

from clients.valkey_client import ValkeyClient


class TestValkeyClientInit:
    """Connection initialization."""

    def test_connects_with_valid_url(self, valkey):
        """Valid URL creates working connection."""
        assert valkey.ping() is True


class TestBasicOperations:
    """Get/set/delete operations."""

    def test_set_and_get(self, valkey):
        """Set then get returns same value."""
        valkey.set("test:basic", "hello")
        assert valkey.get("test:basic") == "hello"
        valkey.delete("test:basic")

    def test_get_missing_returns_none(self, valkey):
        """Get on non-existent key returns None (not error)."""
        result = valkey.get("test:nonexistent:xyz123")
        assert result is None

    def test_delete_returns_true_when_existed(self, valkey):
        """Delete returns True when key existed."""
        valkey.set("test:delete", "value")
        assert valkey.delete("test:delete") is True

    def test_delete_returns_false_when_missing(self, valkey):
        """Delete returns False when key didn't exist."""
        assert valkey.delete("test:nonexistent:abc456") is False

    def test_exists_true_when_present(self, valkey):
        """Exists returns True for existing key."""
        valkey.set("test:exists", "value")
        assert valkey.exists("test:exists") is True
        valkey.delete("test:exists")

    def test_exists_false_when_missing(self, valkey):
        """Exists returns False for missing key."""
        assert valkey.exists("test:nonexistent:def789") is False


class TestExpiration:
    """TTL functionality."""

    def test_set_with_expiration(self, valkey):
        """Value expires after specified seconds."""
        valkey.set("test:expire", "value", expire_seconds=1)
        assert valkey.get("test:expire") == "value"
        time.sleep(1.1)
        assert valkey.get("test:expire") is None

    def test_ttl_returns_remaining_seconds(self, valkey):
        """TTL returns remaining time."""
        valkey.set("test:ttl", "value", expire_seconds=100)
        ttl = valkey.ttl("test:ttl")
        assert 95 <= ttl <= 100
        valkey.delete("test:ttl")

    def test_ttl_minus_two_for_missing(self, valkey):
        """TTL returns -2 for non-existent key."""
        assert valkey.ttl("test:nonexistent:ghi012") == -2

    def test_ttl_minus_one_for_no_expiry(self, valkey):
        """TTL returns -1 for key with no expiry."""
        valkey.set("test:noexpiry", "value")
        assert valkey.ttl("test:noexpiry") == -1
        valkey.delete("test:noexpiry")

    def test_expire_sets_ttl_on_existing_key(self, valkey):
        """Expire sets TTL on existing key without expiry."""
        valkey.set("test:expire_later", "value")
        assert valkey.ttl("test:expire_later") == -1  # No expiry initially
        result = valkey.expire("test:expire_later", 60)
        assert result is True
        ttl = valkey.ttl("test:expire_later")
        assert 55 <= ttl <= 60
        valkey.delete("test:expire_later")

    def test_expire_returns_false_for_missing_key(self, valkey):
        """Expire returns False when key doesn't exist."""
        result = valkey.expire("test:nonexistent:expire", 60)
        assert result is False


class TestCounter:
    """Increment operations."""

    def test_incr_creates_with_one(self, valkey):
        """Incr on missing key creates with value 1."""
        valkey.delete("test:counter")
        assert valkey.incr("test:counter") == 1
        valkey.delete("test:counter")

    def test_incr_increments(self, valkey):
        """Incr increments existing counter."""
        valkey.delete("test:counter2")
        valkey.incr("test:counter2")
        valkey.incr("test:counter2")
        assert valkey.incr("test:counter2") == 3
        valkey.delete("test:counter2")


class TestJsonHelpers:
    """JSON serialization helpers."""

    def test_json_roundtrip(self, valkey):
        """set_json/get_json preserves structure."""
        data = {"user_id": "123", "roles": ["admin", "user"], "active": True}
        valkey.set_json("test:json", data)
        result = valkey.get_json("test:json")
        assert result == data
        valkey.delete("test:json")

    def test_get_json_missing_returns_none(self, valkey):
        """get_json returns None for missing key."""
        result = valkey.get_json("test:nonexistent:json")
        assert result is None

    def test_get_json_invalid_raises(self, valkey):
        """get_json raises on non-JSON value."""
        valkey.set("test:notjson", "not valid json {")
        with pytest.raises(ValueError):
            valkey.get_json("test:notjson")
        valkey.delete("test:notjson")


class TestHealthCheck:
    """Health check."""

    def test_ping_returns_true(self, valkey):
        """Ping returns True when healthy."""
        assert valkey.ping() is True
