"""
Customer service for CRUD operations.

Handles customer lifecycle: create, read, update, soft delete.
All operations are automatically scoped to the current user via RLS.
"""

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.event_bus import EventBus
from core.events import CustomerCreated
from core.exceptions import NotFoundError
from core.models import Customer, CustomerCreate, CustomerUpdate
from utils.workspace_context import get_current_workspace_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

# Valid columns that can be updated
_UPDATABLE_COLUMNS = {
    "first_name", "last_name", "business_name",
    "email", "phone", "address", "notes",
    "preferred_contact_method", "preferred_time_of_day",
    "reference_id", "referred_by", "stripe_customer_id"
}


@dataclass(frozen=True)
class CustomerPage:
    customers: list[Customer]
    next_cursor: str | None


class CustomerService:
    """Service for customer operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger, event_bus: EventBus):
        self.postgres = postgres
        self.audit = audit
        self.event_bus = event_bus

    def create(self, data: CustomerCreate) -> Customer:
        """
        Create a new customer.

        Args:
            data: Customer creation data

        Returns:
            Created customer
        """
        workspace_id = get_current_workspace_id()
        customer_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO customers (
                id, workspace_id, first_name, last_name, business_name,
                email, phone, address, notes,
                preferred_contact_method, preferred_time_of_day,
                reference_id, referred_by, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                customer_id, workspace_id, data.first_name, data.last_name, data.business_name,
                data.email, data.phone, data.address, data.notes,
                data.preferred_contact_method, data.preferred_time_of_day,
                data.reference_id, data.referred_by, now, now
            )
        )[0]

        customer = Customer.model_validate(row)

        self.audit.log_change(
            entity_type="customer",
            entity_id=customer.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        self.event_bus.publish(CustomerCreated.create(customer=customer))

        return customer

    def get_by_id(self, customer_id: UUID) -> Customer | None:
        """
        Get customer by ID.

        Args:
            customer_id: Customer UUID

        Returns:
            Customer if found, None otherwise.
            RLS automatically filters to current user.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM customers WHERE id = %s AND deleted_at IS NULL",
            (customer_id,)
        )

        if row is None:
            return None

        return Customer.model_validate(row)

    def update(self, customer_id: UUID, data: CustomerUpdate) -> Customer:
        """
        Update customer fields.

        Args:
            customer_id: Customer UUID
            data: Fields to update (only non-None fields are changed)

        Returns:
            Updated customer

        Raises:
            ValueError: If customer not found
        """
        # Get current state for audit
        current = self.get_by_id(customer_id)
        if current is None:
            raise NotFoundError(f"Customer {customer_id} not found")

        # Build SET clause from non-None fields
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current  # Nothing to update

        # Warn about unknown fields
        for field in updates:
            if field not in _UPDATABLE_COLUMNS:
                logger.warning(
                    f"Attempted to update unknown field '{field}' on customer {customer_id}"
                )

        # Filter to only valid columns
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
        params.append(customer_id)

        row = self.postgres.execute_returning(
            f"""
            UPDATE customers
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params)
        )[0]

        updated = Customer.model_validate(row)

        # Log changes
        changes = compute_changes(
            current.model_dump(mode="json"),
            updated.model_dump(mode="json")
        )
        if changes:
            self.audit.log_change(
                entity_type="customer",
                entity_id=customer_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return updated

    def delete(self, customer_id: UUID) -> bool:
        """
        Soft delete a customer.

        Args:
            customer_id: Customer UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(customer_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE customers
            SET deleted_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now_utc(), now_utc(), customer_id)
        )

        self.audit.log_change(
            entity_type="customer",
            entity_id=customer_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True

    def list_page(
        self,
        search: str | None,
        limit: int,
        cursor: str | None,
    ) -> CustomerPage:
        """List one stable customer page ordered by ``(created_at, id)``."""
        if limit < 1:
            raise ValueError("Customer page limit must be positive")

        conditions = ["deleted_at IS NULL"]
        params: list[object] = []
        if search:
            terms = search.split()
            columns = """(first_name ILIKE %s
                        OR last_name ILIKE %s
                        OR business_name ILIKE %s
                        OR email ILIKE %s
                        OR phone ILIKE %s)"""
            term_clauses = []
            for term in terms:
                if term:
                    pattern = f"%{term}%"
                    term_clauses.append(columns)
                    params.extend([pattern] * 5)
            if term_clauses:
                conditions.append(f"({') AND ('.join(term_clauses)})")

        if cursor is not None:
            created_at, customer_id = _decode_customer_cursor(cursor)
            conditions.append("(created_at, id) < (%s, %s)")
            params.extend((created_at, customer_id))

        params.append(limit + 1)
        rows = self.postgres.execute(
            f"""
            SELECT * FROM customers
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        customers = [Customer.model_validate(row) for row in rows]
        has_more = len(customers) > limit
        selected = customers[:limit]
        next_cursor = (
            _encode_customer_cursor(selected[-1].created_at, selected[-1].id)
            if has_more
            else None
        )
        return CustomerPage(customers=selected, next_cursor=next_cursor)


def _encode_customer_cursor(created_at: datetime, customer_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(customer_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_customer_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(cursor + padding, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"created_at", "id"}:
            raise ValueError
        if not isinstance(payload["created_at"], str) or not isinstance(payload["id"], str):
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        customer_id = UUID(payload["id"])
    except (binascii.Error, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid customer cursor") from exc
    return created_at, customer_id
