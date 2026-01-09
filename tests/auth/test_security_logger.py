"""Tests for SecurityLogger - auth event audit trail."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from auth.security_logger import SecurityLogger, SecurityEvent
from utils.timezone import now_utc


@pytest.fixture
def security_logger(db):
    """SecurityLogger instance."""
    return SecurityLogger(db)


@pytest.fixture
def cleanup_events(db_admin):
    """Clean up security events after test."""
    yield
    db_admin.execute("DELETE FROM security_events WHERE email LIKE '%@test.example.com'")


class TestLogEvent:
    """Test event logging."""

    def test_logs_event_to_database(self, security_logger, db_admin, cleanup_events):
        """Event is persisted with correct type and data."""
        security_logger.log(
            event=SecurityEvent.MAGIC_LINK_REQUESTED,
            email="logged@test.example.com",
            ip_address="192.168.1.1",
        )

        row = db_admin.execute_single(
            "SELECT event_type, email, ip_address FROM security_events WHERE email = %s",
            ("logged@test.example.com",),
        )
        assert row["event_type"] == "magic_link_requested"
        assert str(row["ip_address"]) == "192.168.1.1"


class TestGetRecentEvents:
    """Test event querying."""

    def test_filters_by_email(self, security_logger, cleanup_events):
        """Returns only events for specified email."""
        security_logger.log(SecurityEvent.MAGIC_LINK_REQUESTED, email="target@test.example.com")
        security_logger.log(SecurityEvent.MAGIC_LINK_REQUESTED, email="other@test.example.com")

        events = security_logger.get_recent_events(email="target@test.example.com")

        assert len(events) == 1
        assert events[0]["email"] == "target@test.example.com"

    def test_newest_first(self, security_logger, cleanup_events):
        """Events returned in reverse chronological order."""
        security_logger.log(SecurityEvent.MAGIC_LINK_REQUESTED, email="first@test.example.com")
        security_logger.log(SecurityEvent.MAGIC_LINK_SENT, email="second@test.example.com")

        events = security_logger.get_recent_events()
        test_events = [e for e in events if e["email"] and "@test.example.com" in e["email"]]

        assert test_events[0]["email"] == "second@test.example.com"

    def test_respects_limit(self, security_logger, cleanup_events):
        """Returns at most limit events."""
        for i in range(10):
            security_logger.log(SecurityEvent.RATE_LIMITED, email=f"limit{i}@test.example.com")

        events = security_logger.get_recent_events(limit=3)

        assert len(events) == 3


class TestRotateLogs:
    """Test log rotation to file."""

    def test_archives_old_events_to_file(self, db_admin, security_logger, tmp_path, cleanup_events):
        """Old events written to file and deleted from database."""
        # Insert old event directly with past timestamp
        past = now_utc() - timedelta(days=10)
        db_admin.execute_returning(
            """INSERT INTO security_events (event_type, email, created_at)
               VALUES (%s, %s, %s) RETURNING id""",
            ("rate_limited", "old@test.example.com", past),
        )

        # Insert recent event
        security_logger.log(SecurityEvent.RATE_LIMITED, email="recent@test.example.com")

        # Rotate logs older than 5 days
        archive_path = tmp_path / "security_events.jsonl"
        count = security_logger.rotate_logs(older_than_days=5, output_path=archive_path)

        assert count == 1

        # Old event should be in file
        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["email"] == "old@test.example.com"

        # Old event should be deleted from DB
        old_events = security_logger.get_recent_events(email="old@test.example.com")
        assert len(old_events) == 0

        # Recent event should still exist
        recent_events = security_logger.get_recent_events(email="recent@test.example.com")
        assert len(recent_events) == 1
