"""
Universal audit trail for all entity changes.

Every mutation to every entity is logged here. The audit log is:
- Append-only (entries never modified or deleted)
- Workspace-attributed (which tenant made the change)
- Detailed (captures old and new values)

Audit records are tenant scoped through the same workspace RLS policy as CRM
business data.
"""

from enum import Enum
from uuid import UUID, uuid4
from typing import Any

from clients.postgres_client import PostgresClient
from utils.workspace_context import get_current_workspace_id
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
    ) -> None:
        """
        Log an entity change.

        Args:
            entity_type: Type of entity ("customer", "ticket", etc.)
            entity_id: ID of the entity
            action: The action performed (CREATE, UPDATE, DELETE)
            changes: The changes made (format depends on action)

        Changes format by action:
        - CREATE: {"created": {full entity data}}
        - UPDATE: {"field": {"old": old_val, "new": new_val}, ...}
        - DELETE: {"deleted": {full entity data at deletion}}
        """
        from psycopg.types.json import Json

        workspace_id = get_current_workspace_id()

        self.postgres.execute(
            """
            INSERT INTO audit_log (id, workspace_id, entity_type, entity_id, action, changes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                workspace_id,
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
            SELECT id, workspace_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE entity_type = %s AND entity_id = %s
            ORDER BY created_at DESC
            """,
            (entity_type, entity_id)
        )

    def get_workspace_activity(
        self,
        workspace_id: UUID | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get recent activity by workspace.

        Args:
            workspace_id: Workspace to get activity for (defaults to current context)
            limit: Maximum entries to return

        Returns:
            List of audit entries, newest first.
        """
        if workspace_id is None:
            workspace_id = get_current_workspace_id()

        return self.postgres.execute(
            """
            SELECT id, workspace_id, entity_type, entity_id, action, changes, created_at
            FROM audit_log
            WHERE workspace_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (workspace_id, limit)
        )
