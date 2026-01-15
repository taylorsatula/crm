"""
Line item service for ticket line items.

Manages line items (services/products) on tickets. Line items reference
the service catalog but store the price at time of creation for historical accuracy.
"""

import logging
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models import LineItem, LineItemCreate, LineItemUpdate, TicketStatus
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

_UPDATABLE_COLUMNS = {
    "description", "quantity", "unit_price_cents",
    "total_price_cents", "duration_minutes"
}


class LineItemService:
    """Service for line item operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, ticket_id: UUID, data: LineItemCreate) -> LineItem:
        """
        Create a new line item on a ticket.

        Args:
            ticket_id: Ticket to add line item to
            data: Line item creation data

        Returns:
            Created line item

        Raises:
            ValueError: If ticket is closed/cancelled or not found
        """
        user_id = get_current_user_id()

        # Check ticket status
        ticket = self.postgres.execute_single(
            "SELECT status FROM tickets WHERE id = %s",
            (ticket_id,)
        )
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found")

        ticket_status = TicketStatus(ticket["status"])
        if ticket_status == TicketStatus.COMPLETED:
            raise ValueError(f"Ticket {ticket_id} is closed")
        if ticket_status == TicketStatus.CANCELLED:
            raise ValueError(f"Ticket {ticket_id} is cancelled")

        # If no price provided, fetch default from service
        total_price_cents = data.total_price_cents
        unit_price_cents = data.unit_price_cents

        if total_price_cents is None:
            if unit_price_cents is not None:
                # Model validator should have computed this, but be safe
                total_price_cents = data.quantity * unit_price_cents
            else:
                # Fall back to service default price
                service = self.postgres.execute_single(
                    "SELECT default_price_cents, unit_price_cents FROM services WHERE id = %s AND deleted_at IS NULL",
                    (data.service_id,)
                )
                if service is None:
                    raise ValueError(f"Service {data.service_id} not found")

                if service["default_price_cents"] is not None:
                    total_price_cents = service["default_price_cents"]
                elif service["unit_price_cents"] is not None:
                    unit_price_cents = service["unit_price_cents"]
                    total_price_cents = data.quantity * unit_price_cents
                else:
                    raise ValueError(f"Service {data.service_id} has no default price")

        line_item_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO line_items (
                id, user_id, ticket_id, service_id,
                description, quantity, unit_price_cents, total_price_cents,
                duration_minutes, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING *
            """,
            (
                line_item_id, user_id, ticket_id, data.service_id,
                data.description, data.quantity, unit_price_cents, total_price_cents,
                data.duration_minutes, now, now
            )
        )[0]

        line_item = LineItem.model_validate(row)

        self.audit.log_change(
            entity_type="line_item",
            entity_id=line_item.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return line_item

    def get_by_id(self, line_item_id: UUID) -> LineItem | None:
        """
        Get line item by ID.

        Args:
            line_item_id: Line item UUID

        Returns:
            Line item if found and not deleted, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM line_items WHERE id = %s AND deleted_at IS NULL",
            (line_item_id,)
        )

        if row is None:
            return None

        return LineItem.model_validate(row)

    def update(self, line_item_id: UUID, data: LineItemUpdate) -> LineItem:
        """
        Update line item fields.

        Args:
            line_item_id: Line item UUID
            data: Fields to update

        Returns:
            Updated line item

        Raises:
            ValueError: If line item not found or ticket is closed
        """
        current = self.get_by_id(line_item_id)
        if current is None:
            raise ValueError(f"Line item {line_item_id} not found")

        # Check ticket status
        ticket = self.postgres.execute_single(
            "SELECT status FROM tickets WHERE id = %s",
            (current.ticket_id,)
        )
        if ticket is None:
            raise ValueError(f"Ticket {current.ticket_id} not found")

        ticket_status = TicketStatus(ticket["status"])
        if ticket_status == TicketStatus.COMPLETED:
            raise ValueError(f"Ticket {current.ticket_id} is closed")
        if ticket_status == TicketStatus.CANCELLED:
            raise ValueError(f"Ticket {current.ticket_id} is cancelled")

        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current

        for field in updates:
            if field not in _UPDATABLE_COLUMNS:
                logger.warning(
                    f"Attempted to update unknown field '{field}' on line_item {line_item_id}"
                )

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
        params.append(line_item_id)

        row = self.postgres.execute_returning(
            f"""
            UPDATE line_items
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params)
        )[0]

        updated = LineItem.model_validate(row)

        changes = compute_changes(
            current.model_dump(mode="json"),
            updated.model_dump(mode="json")
        )
        if changes:
            self.audit.log_change(
                entity_type="line_item",
                entity_id=line_item_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return updated

    def delete(self, line_item_id: UUID) -> bool:
        """
        Soft delete a line item.

        Args:
            line_item_id: Line item UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(line_item_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE line_items
            SET deleted_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now_utc(), now_utc(), line_item_id)
        )

        self.audit.log_change(
            entity_type="line_item",
            entity_id=line_item_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True

    def list_for_ticket(self, ticket_id: UUID) -> list[LineItem]:
        """
        List all line items for a ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            List of line items ordered by creation time
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM line_items
            WHERE ticket_id = %s AND deleted_at IS NULL
            ORDER BY created_at ASC
            """,
            (ticket_id,)
        )

        return [LineItem.model_validate(row) for row in rows]
