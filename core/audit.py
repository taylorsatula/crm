"""
Universal audit trail for all entity changes.

Every mutation to every entity is logged here. The audit log is:
- Append-only (entries never modified or deleted)
- User-attributed (who made the change)
- Detailed (captures old and new values)

The audit_log table has NO RLS - all audit entries are visible regardless of
user context. This is intentional for administrative oversight.
"""

from enum import Enum
from uuid import UUID, uuid4
from typing import Any

from clients.postgres_client import PostgresClient
from utils.user_context import get_current_user_id
from utils.timezone import now_utc


class AuditAction(Enum):
    """Type of change made to an entity."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


def compute_changes(
    old: dict[str, Any],
    new: dict[str, Any],
    exclude_fields: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """
    Compute changes between two entity states.

    Args:
        old: Previous state of entity
        new: New state of entity
        exclude_fields: Fields to ignore (defaults to {"updated_at"})

    Returns:
        Dict of {field: {"old": old_val, "new": new_val}} for changed fields.
        Empty dict if no changes.
    """
    exclude = exclude_fields or {"updated_at"}
    changes = {}

    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        if key in exclude:
            continue

        old_val = old.get(key)
        new_val = new.get(key)

        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}

    return changes


class AuditLogger:
    """
    Universal audit trail for all entity changes.

    IMPORTANT: Always use model_dump(mode="json") when passing Pydantic models
    to ensure UUIDs and datetimes are serialized to JSON-compatible strings.

    Usage:
        audit = AuditLogger(postgres)

        # Log creation - use mode="json" for JSON serialization
        audit.log_change(
            entity_type="customer",
            entity_id=customer.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        # Log update - use mode="json" for both old and new
        changes = compute_changes(
            old.model_dump(mode="json"),
            new.model_dump(mode="json")
        )
        audit.log_change(
            entity_type="customer",
            entity_id=customer.id,
            action=AuditAction.UPDATE,
            changes=changes
        )

        # Log deletion
        audit.log_change(
            entity_type="customer",
            entity_id=customer.id,
            action=AuditAction.DELETE,
            changes={"deleted": customer.model_dump(mode="json")}
        )

        # Get history
        history = audit.get_entity_history("customer", customer.id)
    """

    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    def log_change(
        self,
        entity_type: str,
        entity_id: UUID,
        action: AuditAction,
        changes: dict[str, Any],
        user_id: UUID | None = None
    ) -> None:
        """
        Log an entity change.

        Args:
            entity_type: Type of entity ("customer", "ticket", etc.)
            entity_id: ID of the entity
            action: The action performed (CREATE, UPDATE, DELETE)
            changes: The changes made (format depends on action)
            user_id: User who made change (defaults to current context)

        Changes format by action:
        - CREATE: {"created": {full entity data}}
        - UPDATE: {"field": {"old": old_val, "new": new_val}, ...}
        - DELETE: {"deleted": {full entity data at deletion}}
        """
        from psycopg.types.json import Json

        if user_id is None:
            user_id = get_current_user_id()

        # audit_log has NO RLS so regular execute() works
        self.postgres.execute(
            """
            INSERT INTO audit_log (id, user_id, entity_type, entity_id, action, changes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                user_id,
                entity_type,
                entity_id,
                action.value,
                Json(changes),
                now_utc()
            )
        )

    def get_entity_history(
        self,
        entity_type: str,
        entity_id: UUID
    ) -> list[dict[str, Any]]:
        """
        Get full audit history for an entity.

        Args:
            entity_type: Type of entity ("customer", "ticket", etc.)
            entity_id: ID of the entity

        Returns:
            List of audit entries, newest first.
        """
        return self.postgres.execute(
            """
            SELECT id, user_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE entity_type = %s AND entity_id = %s
            ORDER BY created_at DESC
            """,
            (entity_type, entity_id)
        )

    def get_user_activity(
        self,
        user_id: UUID | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get recent activity by user.

        Args:
            user_id: User to get activity for (defaults to current context)
            limit: Maximum entries to return

        Returns:
            List of audit entries, newest first.
        """
        if user_id is None:
            user_id = get_current_user_id()

        return self.postgres.execute(
            """
            SELECT id, user_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit)
        )
