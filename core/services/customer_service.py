"""
Customer service for CRUD operations.

Handles customer lifecycle: create, read, update, soft delete.
All operations are automatically scoped to the current user via RLS.
"""

import logging
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models import Customer, CustomerCreate, CustomerUpdate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

# Valid columns that can be updated
_UPDATABLE_COLUMNS = {
    "first_name", "last_name", "business_name",
    "email", "phone", "address", "notes",
    "preferred_contact_method", "preferred_time_of_day",
    "reference_id", "referred_by", "stripe_customer_id"
}


class CustomerService:
    """Service for customer operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: CustomerCreate) -> Customer:
        """
        Create a new customer.

        Args:
            data: Customer creation data

        Returns:
            Created customer
        """
        user_id = get_current_user_id()
        customer_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO customers (
                id, user_id, first_name, last_name, business_name,
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
                customer_id, user_id, data.first_name, data.last_name, data.business_name,
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
            raise ValueError(f"Customer {customer_id} not found")

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

    def list_all(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> list[Customer]:
        """
        List customers with pagination.

        Args:
            limit: Maximum results (default 50)
            offset: Offset for pagination

        Returns:
            List of customers, ordered by created_at DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM customers
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset)
        )

        return [Customer.model_validate(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> list[Customer]:
        """
        Search customers by name, email, or phone.

        Uses ILIKE for case-insensitive partial matching.

        Args:
            query: Search string
            limit: Maximum results

        Returns:
            Matching customers
        """
        pattern = f"%{query}%"

        rows = self.postgres.execute(
            """
            SELECT * FROM customers
            WHERE deleted_at IS NULL
              AND (first_name ILIKE %s
               OR last_name ILIKE %s
               OR business_name ILIKE %s
               OR email ILIKE %s
               OR phone ILIKE %s)
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (pattern, pattern, pattern, pattern, pattern, limit)
        )

        return [Customer.model_validate(row) for row in rows]
