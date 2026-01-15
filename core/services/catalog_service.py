"""
Catalog service for service catalog (pricing/offerings).

Manages the service catalog - the types of services offered with their
pricing models. Services can be fixed price, per-unit, or flexible.
"""

import logging
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models import Service, ServiceCreate, ServiceUpdate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

_UPDATABLE_COLUMNS = {
    "name", "description", "pricing_type",
    "default_price_cents", "unit_price_cents", "unit_label",
    "is_active", "display_order"
}


class CatalogService:
    """Service for service catalog operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: ServiceCreate) -> Service:
        """
        Create a new service in the catalog.

        Args:
            data: Service creation data

        Returns:
            Created service
        """
        user_id = get_current_user_id()
        service_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO services (
                id, user_id, name, description,
                pricing_type, default_price_cents, unit_price_cents, unit_label,
                is_active, display_order, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                service_id, user_id, data.name, data.description,
                data.pricing_type.value, data.default_price_cents, data.unit_price_cents, data.unit_label,
                data.is_active, data.display_order, now, now
            )
        )[0]

        service = Service.model_validate(row)

        self.audit.log_change(
            entity_type="service",
            entity_id=service.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return service

    def get_by_id(self, service_id: UUID) -> Service | None:
        """
        Get service by ID.

        Args:
            service_id: Service UUID

        Returns:
            Service if found and not deleted, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM services WHERE id = %s AND deleted_at IS NULL",
            (service_id,)
        )

        if row is None:
            return None

        return Service.model_validate(row)

    def list_active(self) -> list[Service]:
        """
        List all active services.

        Returns:
            List of active services ordered by name
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM services
            WHERE is_active = true AND deleted_at IS NULL
            ORDER BY name ASC
            """
        )

        return [Service.model_validate(row) for row in rows]

    def list_all(self) -> list[Service]:
        """
        List all services including inactive (but not deleted).

        Returns:
            List of all non-deleted services ordered by name
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM services
            WHERE deleted_at IS NULL
            ORDER BY name ASC
            """
        )

        return [Service.model_validate(row) for row in rows]

    def update(self, service_id: UUID, data: ServiceUpdate) -> Service:
        """
        Update service fields.

        Args:
            service_id: Service UUID
            data: Fields to update

        Returns:
            Updated service

        Raises:
            ValueError: If service not found
        """
        current = self.get_by_id(service_id)
        if current is None:
            raise ValueError(f"Service {service_id} not found")

        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current

        for field in updates:
            if field not in _UPDATABLE_COLUMNS:
                logger.warning(
                    f"Attempted to update unknown field '{field}' on service {service_id}"
                )

        # Convert enum to string if present
        if "pricing_type" in updates and hasattr(updates["pricing_type"], "value"):
            updates["pricing_type"] = updates["pricing_type"].value

        valid_updates = {k: v for k, v in updates.items() if k in _UPDATABLE_COLUMNS}
        if not valid_updates:
            return current

        set_parts = []
        params = []
        for field, value in valid_updates.items():
            set_parts.append(f"{field} = %s")
            params.append(value)

        set_parts.append("updated_at = %s")
        params.append(now_utc())
        params.append(service_id)

        row = self.postgres.execute_returning(
            f"""
            UPDATE services
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params)
        )[0]

        updated = Service.model_validate(row)

        changes = compute_changes(
            current.model_dump(mode="json"),
            updated.model_dump(mode="json")
        )
        if changes:
            self.audit.log_change(
                entity_type="service",
                entity_id=service_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return updated

    def delete(self, service_id: UUID) -> bool:
        """
        Soft delete a service.

        Args:
            service_id: Service UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(service_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE services
            SET deleted_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now_utc(), now_utc(), service_id)
        )

        self.audit.log_change(
            entity_type="service",
            entity_id=service_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True
