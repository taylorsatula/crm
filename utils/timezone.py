"""UTC-everywhere time handling. Eliminates timezone bugs at the source."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    """
    Current time in UTC.

    Use this instead of datetime.now() everywhere.
    """
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """
    Convert a datetime to UTC.

    Raises ValueError if datetime is naive (no timezone).
    """
    if dt.tzinfo is None:
        raise ValueError(
            "Cannot convert naive datetime to UTC. Datetime must be timezone-aware."
        )
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime, tz_name: str) -> datetime:
    """
    Convert UTC datetime to local timezone for display.

    ONLY use this at display boundaries - when rendering for humans.
    All internal operations should remain in UTC.

    Args:
        dt: UTC datetime
        tz_name: IANA timezone name (e.g., "America/Chicago")

    Raises:
        ValueError: If datetime is naive or timezone name is invalid
    """
    if dt.tzinfo is None:
        raise ValueError(
            "Cannot convert naive datetime. Datetime must be timezone-aware."
        )

    try:
        local_tz = ZoneInfo(tz_name)
    except KeyError:
        raise ValueError(f"Unknown timezone: {tz_name}")

    return dt.astimezone(local_tz)


def parse_iso(iso_string: str) -> datetime:
    """
    Parse ISO 8601 datetime string to UTC datetime.

    Raises ValueError if string has no timezone info.
    """
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        raise ValueError(
            "Cannot parse naive datetime string. "
            "Include timezone offset (e.g., 'Z' or '+00:00')."
        )
    return to_utc(dt)
