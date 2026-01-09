"""Tests for RateLimiter - magic link request throttling."""

import pytest

from auth.rate_limiter import RateLimiter
from auth.config import AuthConfig
from auth.exceptions import RateLimitedError


@pytest.fixture
def config():
    """Test config with low attempts for faster tests."""
    return AuthConfig(
        rate_limit_attempts=3,
        rate_limit_window_minutes=5,  # Minimum allowed
    )


@pytest.fixture
def rate_limiter(valkey, config):
    """RateLimiter with test config."""
    limiter = RateLimiter(valkey, config)
    yield limiter
    # Cleanup test keys
    for key in valkey._client.keys("ratelimit:magic_link:*"):
        valkey._client.delete(key)


class TestCheckRateLimit:
    """Test rate limit checking and incrementing."""

    def test_first_attempt_passes(self, rate_limiter):
        """First attempt does not raise."""
        rate_limiter.check_rate_limit("user@example.com")

    def test_within_limit_passes(self, rate_limiter, config):
        """Attempts within limit pass."""
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("allowed@example.com")

    def test_exceeds_limit_raises(self, rate_limiter, config):
        """Exceeding limit raises RateLimitedError."""
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("blocked@example.com")

        with pytest.raises(RateLimitedError):
            rate_limiter.check_rate_limit("blocked@example.com")

    def test_error_includes_retry_after(self, rate_limiter, config):
        """RateLimitedError includes positive retry_after_seconds."""
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("retry@example.com")

        with pytest.raises(RateLimitedError) as exc_info:
            rate_limiter.check_rate_limit("retry@example.com")

        assert exc_info.value.retry_after_seconds > 0

    def test_different_emails_tracked_separately(self, rate_limiter, config):
        """Each email has its own counter."""
        # Max out user1
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("user1@example.com")

        # user2 should still be allowed
        rate_limiter.check_rate_limit("user2@example.com")

    def test_emails_normalized_lowercase(self, rate_limiter, config):
        """Email lookups are case-insensitive."""
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("CASE@example.com")

        # Same email, different case
        with pytest.raises(RateLimitedError):
            rate_limiter.check_rate_limit("case@EXAMPLE.com")


class TestSlidingWindow:
    """Test sliding window TTL behavior."""

    def test_hammering_extends_lockout(self, rate_limiter, config, valkey):
        """Each attempt resets TTL - hammering extends lockout."""
        email = "hammer@example.com"
        key = f"ratelimit:magic_link:{email}"

        # Exhaust attempts
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit(email)

        # Get initial TTL
        initial_ttl = valkey.ttl(key)

        # Hammer while rate limited (this resets TTL each time)
        for _ in range(3):
            try:
                rate_limiter.check_rate_limit(email)
            except RateLimitedError:
                pass

        # TTL should have reset to full window
        new_ttl = valkey.ttl(key)
        assert new_ttl >= initial_ttl  # Should be reset, not decreased


class TestResetRateLimit:
    """Test rate limit reset."""

    def test_reset_allows_new_attempts(self, rate_limiter, config):
        """Reset clears counter, allowing new attempts."""
        # Max out attempts
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("reset@example.com")

        # Reset
        rate_limiter.reset_rate_limit("reset@example.com")

        # Should be allowed again
        rate_limiter.check_rate_limit("reset@example.com")

    def test_reset_nonexistent_does_not_error(self, rate_limiter):
        """Resetting an email with no history doesn't raise."""
        rate_limiter.reset_rate_limit("never@example.com")


class TestGetRemainingAttempts:
    """Test remaining attempts query."""

    def test_returns_max_when_no_attempts(self, rate_limiter, config):
        """Returns max attempts when email has no history."""
        remaining = rate_limiter.get_remaining_attempts("fresh@example.com")
        assert remaining == config.rate_limit_attempts

    def test_decrements_with_attempts(self, rate_limiter, config):
        """Returns correct count after attempts."""
        rate_limiter.check_rate_limit("counting@example.com")
        rate_limiter.check_rate_limit("counting@example.com")

        remaining = rate_limiter.get_remaining_attempts("counting@example.com")
        assert remaining == config.rate_limit_attempts - 2

    def test_returns_zero_when_exhausted(self, rate_limiter, config):
        """Returns 0 when all attempts used."""
        for _ in range(config.rate_limit_attempts):
            rate_limiter.check_rate_limit("exhausted@example.com")

        remaining = rate_limiter.get_remaining_attempts("exhausted@example.com")
        assert remaining == 0
