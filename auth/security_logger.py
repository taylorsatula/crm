"""Security event logging for auth audit trail.

Append-only log to security_events table (no RLS).
Includes log rotation to archive old events to file.
"""

import json
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from clients.postgres_client import PostgresClient
from utils.timezone import now_utc


class SecurityEvent(Enum):
    """Auth security event types."""

    MAGIC_LINK_REQUESTED = "magic_link_requested"
    MAGIC_LINK_SENT = "magic_link_sent"
    MAGIC_LINK_VERIFIED = "magic_link_verified"
    MAGIC_LINK_FAILED = "magic_link_failed"
    MAGIC_LINK_EXPIRED = "magic_link_expired"
    MAGIC_LINK_ALREADY_USED = "magic_link_already_used"
    SESSION_CREATED = "session_created"
    SESSION_EXTENDED = "session_extended"
    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"
    RATE_LIMITED = "rate_limited"
    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    USER_ACTIVATED = "user_activated"


class SecurityLogger:
    """Append-only security event logger with rotation."""

    def __init__(self, postgres: PostgresClient):
        self._db = postgres

    def log(
        self,
        event: SecurityEvent,
        email: str | None = None,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log security event to database."""
        self._db.execute_returning(
            """INSERT INTO security_events
               (event_type, email, user_id, ip_address, user_agent, details, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                event.value,
                email,
                str(user_id) if user_id else None,
                ip_address,
                user_agent,
                Json(details) if details else None,
                now_utc(),
            ),
        )

    def get_recent_events(
        self,
        email: str | None = None,
        user_id: UUID | None = None,
        event_type: SecurityEvent | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query recent security events with optional filters."""
        conditions = []
        params = []

        if email:
            conditions.append("email = %s")
            params.append(email)

        if user_id:
            conditions.append("user_id = %s")
            params.append(str(user_id))

        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        return self._db.execute(
            f"""SELECT id, event_type, email, user_id, ip_address, user_agent, details, created_at
                FROM security_events
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s""",
            tuple(params),
        )

    def rotate_logs(self, older_than_days: int, output_path: Path) -> int:
        """Archive old logs to file and delete from database.

        Args:
            older_than_days: Archive events older than this many days
            output_path: Path to write JSON lines file

        Returns:
            Number of events archived and deleted
        """
        cutoff = now_utc() - timedelta(days=older_than_days)

        # Fetch old events
        events = self._db.execute(
            """SELECT id, event_type, email, user_id, ip_address, user_agent, details, created_at
               FROM security_events
               WHERE created_at < %s
               ORDER BY created_at ASC""",
            (cutoff,),
        )

        if not events:
            return 0

        # Write to file (JSON lines format, append mode)
        with open(output_path, "a") as f:
            for event in events:
                # Convert datetime and UUID to strings for JSON
                record = {
                    "id": str(event["id"]),
                    "event_type": event["event_type"],
                    "email": event["email"],
                    "user_id": str(event["user_id"]) if event["user_id"] else None,
                    "ip_address": str(event["ip_address"]) if event["ip_address"] else None,
                    "user_agent": event["user_agent"],
                    "details": event["details"],
                    "created_at": event["created_at"].isoformat(),
                }
                f.write(json.dumps(record) + "\n")

        # Delete archived events
        self._db.execute_returning(
            "DELETE FROM security_events WHERE created_at < %s RETURNING id",
            (cutoff,),
        )

        return len(events)
