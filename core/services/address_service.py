"""
Address service for CRUD operations.

Handles service location addresses for customers.
Addresses are hard-deleted (not soft) since they CASCADE from customer.
"""

import logging
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.models import Address, AddressCreate, AddressUpdate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

# Valid columns that can be updated
_UPDATABLE_COLUMNS = {
    "label", "street", "street2", "city", "state", "zip", "notes", "is_primary"
}


class AddressService:
    """Service for address operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: AddressCreate) -> Address:
        """
        Create a new address for a customer.

        Args:
            data: Address creation data including customer_id

        Returns:
            Created address
        """
        user_id = get_current_user_id()
        address_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO addresses (
                id, user_id, customer_id,
                label, street, street2, city, state, zip,
                notes, is_primary, created_at, updated_at
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                address_id, user_id, data.customer_id,
                data.label, data.street, data.street2, data.city, data.state, data.zip,
                data.notes, data.is_primary, now, now
            )
        )[0]

        address = Address.model_validate(row)

        self.audit.log_change(
            entity_type="address",
            entity_id=address.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return address

    def get_by_id(self, address_id: UUID) -> Address | None:
        """
        Get address by ID.

        Args:
            address_id: Address UUID

        Returns:
            Address if found, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM addresses WHERE id = %s",
            (address_id,)
        )

        if row is None:
            return None

        return Address.model_validate(row)

    def list_for_customer(self, customer_id: UUID) -> list[Address]:
        """
        List all addresses for a customer.

        Args:
            customer_id: Customer UUID

        Returns:
            List of addresses, primary first then by created_at
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM addresses
            WHERE customer_id = %s
            ORDER BY is_primary DESC, created_at ASC
            """,
            (customer_id,)
        )

        return [Address.model_validate(row) for row in rows]

    def update(self, address_id: UUID, data: AddressUpdate) -> Address:
        """
        Update address fields.

        Args:
            address_id: Address UUID
            data: Fields to update

        Returns:
            Updated address

        Raises:
            ValueError: If address not found
        """
        current = self.get_by_id(address_id)
        if current is None:
            raise ValueError(f"Address {address_id} not found")

        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current

        # Warn about unknown fields
        for field in updates:
            if field not in _UPDATABLE_COLUMNS:
                logger.warning(
                    f"Attempted to update unknown field '{field}' on address {address_id}"
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
        params.append(address_id)

        row = self.postgres.execute_returning(
            f"""
            UPDATE addresses
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params)
        )[0]

        updated = Address.model_validate(row)

        changes = compute_changes(
            current.model_dump(),
            updated.model_dump()
        )
        if changes:
            self.audit.log_change(
                entity_type="address",
                entity_id=address_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return updated

    def delete(self, address_id: UUID) -> bool:
        """
        Hard delete an address.

        Args:
            address_id: Address UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(address_id)
        if current is None:
            return False

        self.postgres.execute(
            "DELETE FROM addresses WHERE id = %s",
            (address_id,)
        )

        self.audit.log_change(
            entity_type="address",
            entity_id=address_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True
