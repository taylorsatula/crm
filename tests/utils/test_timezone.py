"""Tests for utils/timezone.py - UTC-everywhere time handling."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from utils.timezone import now_utc, to_utc, to_local, parse_iso


class TestNowUtc:
    """Tests for now_utc()."""

    def test_returns_timezone_aware(self):
        """Result must have tzinfo set (not naive)."""
        result = now_utc()
        assert result.tzinfo is not None

    def test_is_utc(self):
        """Result timezone must be specifically UTC."""
        result = now_utc()
        assert result.tzinfo == timezone.utc


class TestToUtc:
    """Tests for to_utc()."""

    def test_raises_on_naive(self):
        """Naive datetime must raise ValueError."""
        naive = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="naive"):
            to_utc(naive)

    def test_converts_other_timezone(self):
        """Chicago 12:00 in January should become UTC 18:00."""
        # Chicago is UTC-6 in January (no DST)
        chicago = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("America/Chicago"))
        result = to_utc(chicago)
        assert result.tzinfo == timezone.utc
        assert result.hour == 18

    def test_utc_passes_through(self):
        """UTC datetime should pass through unchanged."""
        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = to_utc(utc_time)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12


class TestToLocal:
    """Tests for to_local()."""

    def test_converts_correctly(self):
        """UTC 18:00 should become Chicago 12:00 in January."""
        utc_time = datetime(2024, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
        result = to_local(utc_time, "America/Chicago")
        assert result.hour == 12

    def test_raises_on_naive(self):
        """Naive datetime must raise ValueError."""
        naive = datetime(2024, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="naive"):
            to_local(naive, "America/Chicago")

    def test_raises_on_invalid_timezone(self):
        """Invalid timezone name must raise ValueError."""
        utc_time = now_utc()
        with pytest.raises(ValueError, match="Unknown timezone"):
            to_local(utc_time, "Not/A/Timezone")


class TestParseIso:
    """Tests for parse_iso()."""

    def test_handles_zulu(self):
        """ISO string with Z suffix should parse to UTC."""
        result = parse_iso("2024-01-01T12:00:00Z")
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_handles_offset(self):
        """ISO string with offset should convert to UTC."""
        # -06:00 offset means local time is 6 hours behind UTC
        # So 12:00-06:00 = 18:00 UTC
        result = parse_iso("2024-01-01T12:00:00-06:00")
        assert result.tzinfo == timezone.utc
        assert result.hour == 18

    def test_raises_on_naive(self):
        """ISO string without timezone must raise ValueError."""
        with pytest.raises(ValueError, match="timezone"):
            parse_iso("2024-01-01T12:00:00")

    def test_handles_positive_offset(self):
        """ISO string with positive offset should convert to UTC."""
        # +05:30 offset means local time is 5.5 hours ahead of UTC
        # So 12:00+05:30 = 06:30 UTC
        result = parse_iso("2024-01-01T12:00:00+05:30")
        assert result.tzinfo == timezone.utc
        assert result.hour == 6
        assert result.minute == 30
