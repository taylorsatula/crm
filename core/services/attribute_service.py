"""
Attribute service for customer attributes.

Attributes are key-value pairs attached to customers. They can be manually
entered or extracted from notes by LLM. Attributes are unique per customer+key.
"""

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction
from core.models import Attribute, AttributeCreate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


class AttributeService:
    """Service for attribute operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: AttributeCreate) -> Attribute:
        """
        Create or update an attribute.

        If an attribute with the same customer_id + key exists, it will be updated.

        Args:
            data: Attribute creation data

        Returns:
            Created or updated attribute
        """
        user_id = get_current_user_id()
        now = now_utc()

        # Check if attribute already exists for this customer+key
        existing = self.get_for_customer(data.customer_id, data.key)

        # Serialize value to JSON
        value_json = json.dumps(data.value)

        if existing:
            # Update existing attribute
            row = self.postgres.execute_returning(
                """
                UPDATE attributes
                SET value = %s, source_type = %s, source_note_id = %s,
                    confidence = %s, updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    value_json, data.source_type, data.source_note_id,
                    data.confidence, now, existing.id
                )
            )[0]

            attr = Attribute.model_validate(row)

            self.audit.log_change(
                entity_type="attribute",
                entity_id=attr.id,
                action=AuditAction.UPDATE,
                changes={
                    "key": data.key,
                    "old_value": existing.value,
                    "new_value": data.value
                }
            )

            return attr

        # Create new attribute
        attr_id = uuid4()

        row = self.postgres.execute_returning(
            """
            INSERT INTO attributes (
                id, user_id, customer_id, key, value,
                source_type, source_note_id, confidence,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                attr_id, user_id, data.customer_id, data.key, value_json,
                data.source_type, data.source_note_id, data.confidence,
                now, now
            )
        )[0]

        attr = Attribute.model_validate(row)

        self.audit.log_change(
            entity_type="attribute",
            entity_id=attr.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return attr

    def get_by_id(self, attribute_id: UUID) -> Attribute | None:
        """
        Get attribute by ID.

        Args:
            attribute_id: Attribute UUID

        Returns:
            Attribute if found, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM attributes WHERE id = %s",
            (attribute_id,)
        )

        if row is None:
            return None

        return Attribute.model_validate(row)

    def get_for_customer(self, customer_id: UUID, key: str) -> Attribute | None:
        """
        Get a specific attribute for a customer by key.

        Args:
            customer_id: Customer UUID
            key: Attribute key

        Returns:
            Attribute if found, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM attributes WHERE customer_id = %s AND key = %s",
            (customer_id, key)
        )

        if row is None:
            return None

        return Attribute.model_validate(row)

    def list_for_customer(self, customer_id: UUID) -> list[Attribute]:
        """
        List all attributes for a customer.

        Args:
            customer_id: Customer UUID

        Returns:
            List of attributes ordered by key
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM attributes
            WHERE customer_id = %s
            ORDER BY key ASC
            """,
            (customer_id,)
        )

        return [Attribute.model_validate(row) for row in rows]

    def delete(self, attribute_id: UUID) -> bool:
        """
        Delete an attribute.

        Args:
            attribute_id: Attribute UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(attribute_id)
        if current is None:
            return False

        self.postgres.execute(
            "DELETE FROM attributes WHERE id = %s",
            (attribute_id,)
        )

        self.audit.log_change(
            entity_type="attribute",
            entity_id=attribute_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True

    def bulk_create_from_extraction(
        self,
        customer_id: UUID,
        attributes: dict[str, Any],
        source_note_id: UUID,
        confidence: Decimal
    ) -> list[Attribute]:
        """
        Bulk create attributes from LLM extraction.

        Args:
            customer_id: Customer UUID
            attributes: Dict of key -> value pairs
            source_note_id: Note the attributes were extracted from
            confidence: LLM confidence score

        Returns:
            List of created attributes
        """
        created = []

        for key, value in attributes.items():
            attr = self.create(AttributeCreate(
                customer_id=customer_id,
                key=key,
                value=value,
                source_type="llm_extracted",
                source_note_id=source_note_id,
                confidence=confidence
            ))
            created.append(attr)

        return created
