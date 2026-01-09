"""Rate limiting for magic link requests.

Uses Valkey with sliding window TTL - each attempt resets the expiry.
Attackers bypassing frontend rate limiting hit an ever-extending lockout.
"""

from clients.valkey_client import ValkeyClient
from auth.config import AuthConfig
from auth.exceptions import RateLimitedError


class RateLimiter:
    """Rate limiting for magic link requests using Valkey."""

    KEY_PREFIX = "ratelimit:magic_link:"

    def __init__(self, valkey: ValkeyClient, config: AuthConfig):
        self._valkey = valkey
        self._config = config
        self._window_seconds = config.rate_limit_window_minutes * 60

    def _key(self, email: str) -> str:
        """Generate rate limit key for email (normalized to lowercase)."""
        return f"{self.KEY_PREFIX}{email.lower()}"

    def check_rate_limit(self, email: str) -> None:
        """Check rate limit and increment counter.

        Sliding window: TTL resets on every attempt. Hammering extends lockout.

        Raises:
            RateLimitedError: If rate limit exceeded.
        """
        key = self._key(email)

        # Increment counter
        count = self._valkey.incr(key)

        # Reset TTL on every attempt (sliding window)
        self._valkey.expire(key, self._window_seconds)

        # Check if over limit
        if count > self._config.rate_limit_attempts:
            ttl = self._valkey.ttl(key)
            retry_after = max(ttl, 1)  # At least 1 second
            raise RateLimitedError(retry_after_seconds=retry_after)

    def reset_rate_limit(self, email: str) -> None:
        """Reset rate limit after successful login."""
        key = self._key(email)
        self._valkey.delete(key)

    def get_remaining_attempts(self, email: str) -> int:
        """Get remaining attempts before rate limit."""
        key = self._key(email)
        current = self._valkey.get(key)

        if current is None:
            return self._config.rate_limit_attempts

        count = int(current)
        remaining = self._config.rate_limit_attempts - count
        return max(remaining, 0)
