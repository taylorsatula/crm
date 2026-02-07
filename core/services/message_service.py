"""
Message service for scheduled message management.

Handles scheduling, status transitions, and batch processing of scheduled
messages (reminders, confirmations, custom messages).
"""

import logging
from typing import Callable
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction
from core.models import ScheduledMessage, ScheduledMessageCreate, MessageStatus
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


class MessageService:
    """Service for scheduled message operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def schedule(self, data: ScheduledMessageCreate) -> ScheduledMessage:
        """
        Schedule a new message for future delivery.

        Args:
            data: Message scheduling data

        Returns:
            Scheduled message in PENDING status
        """
        user_id = get_current_user_id()
        message_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO scheduled_messages (
                id, user_id, customer_id, ticket_id,
                message_type, template_name, subject, body,
                scheduled_for, status, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING *
            """,
            (
                message_id, user_id, data.customer_id, data.ticket_id,
                data.message_type.value, data.template_name, data.subject, data.body,
                data.scheduled_for, MessageStatus.PENDING.value, now
            )
        )[0]

        message = ScheduledMessage.model_validate(row)

        self.audit.log_change(
            entity_type="scheduled_message",
            entity_id=message.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return message

    def get_by_id(self, message_id: UUID) -> ScheduledMessage | None:
        """
        Get scheduled message by ID.

        Args:
            message_id: Message UUID

        Returns:
            Message if found, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM scheduled_messages WHERE id = %s",
            (message_id,)
        )

        if row is None:
            return None

        return ScheduledMessage.model_validate(row)

    def mark_sent(self, message_id: UUID) -> ScheduledMessage:
        """
        Mark a message as sent.

        Args:
            message_id: Message UUID

        Returns:
            Updated message with SENT status

        Raises:
            ValueError: If message not found
        """
        current = self.get_by_id(message_id)
        if current is None:
            raise ValueError(f"Message {message_id} not found")

        row = self.postgres.execute_returning(
            """
            UPDATE scheduled_messages
            SET status = %s
            WHERE id = %s
            RETURNING *
            """,
            (MessageStatus.SENT.value, message_id)
        )[0]

        updated = ScheduledMessage.model_validate(row)

        self.audit.log_change(
            entity_type="scheduled_message",
            entity_id=message_id,
            action=AuditAction.UPDATE,
            changes={"status": {"old": current.status.value, "new": MessageStatus.SENT.value}}
        )

        return updated

    def mark_failed(self, message_id: UUID) -> ScheduledMessage:
        """
        Mark a message as failed (gateway error).

        Args:
            message_id: Message UUID

        Returns:
            Updated message with FAILED status

        Raises:
            ValueError: If message not found
        """
        current = self.get_by_id(message_id)
        if current is None:
            raise ValueError(f"Message {message_id} not found")

        row = self.postgres.execute_returning(
            """
            UPDATE scheduled_messages
            SET status = %s
            WHERE id = %s
            RETURNING *
            """,
            (MessageStatus.FAILED.value, message_id)
        )[0]

        updated = ScheduledMessage.model_validate(row)

        self.audit.log_change(
            entity_type="scheduled_message",
            entity_id=message_id,
            action=AuditAction.UPDATE,
            changes={"status": {"old": current.status.value, "new": MessageStatus.FAILED.value}}
        )

        return updated

    def mark_skipped(self, message_id: UUID, reason: str) -> ScheduledMessage:
        """
        Mark a message as skipped (precondition failed - no email, etc.).

        Args:
            message_id: Message UUID
            reason: Why the message was skipped

        Returns:
            Updated message with SKIPPED status

        Raises:
            ValueError: If message not found
        """
        current = self.get_by_id(message_id)
        if current is None:
            raise ValueError(f"Message {message_id} not found")

        row = self.postgres.execute_returning(
            """
            UPDATE scheduled_messages
            SET status = %s
            WHERE id = %s
            RETURNING *
            """,
            (MessageStatus.SKIPPED.value, message_id)
        )[0]

        updated = ScheduledMessage.model_validate(row)

        self.audit.log_change(
            entity_type="scheduled_message",
            entity_id=message_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"old": current.status.value, "new": MessageStatus.SKIPPED.value},
                "skip_reason": reason
            }
        )

        return updated

    def cancel(self, message_id: UUID) -> ScheduledMessage:
        """
        Cancel a pending message.

        Args:
            message_id: Message UUID

        Returns:
            Updated message with CANCELLED status

        Raises:
            ValueError: If message not found or not pending
        """
        current = self.get_by_id(message_id)
        if current is None:
            raise ValueError(f"Message {message_id} not found")

        if current.status != MessageStatus.PENDING:
            raise ValueError(f"Message {message_id} is not pending")

        row = self.postgres.execute_returning(
            """
            UPDATE scheduled_messages
            SET status = %s
            WHERE id = %s
            RETURNING *
            """,
            (MessageStatus.CANCELLED.value, message_id)
        )[0]

        updated = ScheduledMessage.model_validate(row)

        self.audit.log_change(
            entity_type="scheduled_message",
            entity_id=message_id,
            action=AuditAction.UPDATE,
            changes={"status": {"old": current.status.value, "new": MessageStatus.CANCELLED.value}}
        )

        return updated

    def list_pending_for_ticket(self, ticket_id: UUID) -> list[ScheduledMessage]:
        """
        List pending messages for a ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            List of pending messages for the ticket, ordered by scheduled_for ASC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM scheduled_messages
            WHERE ticket_id = %s AND status = %s
            ORDER BY scheduled_for ASC
            """,
            (ticket_id, MessageStatus.PENDING.value)
        )

        return [ScheduledMessage.model_validate(row) for row in rows]

    def list_pending_due(self, limit: int = 100) -> list[ScheduledMessage]:
        """
        List pending messages that are due to be sent.

        Args:
            limit: Maximum results

        Returns:
            List of pending messages where scheduled_for <= now, ordered by scheduled_for
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM scheduled_messages
            WHERE status = %s AND scheduled_for <= %s
            ORDER BY scheduled_for ASC
            LIMIT %s
            """,
            (MessageStatus.PENDING.value, now_utc(), limit)
        )

        return [ScheduledMessage.model_validate(row) for row in rows]

    def list_for_customer(self, customer_id: UUID, limit: int = 50) -> list[ScheduledMessage]:
        """
        List all messages for a customer.

        Args:
            customer_id: Customer UUID
            limit: Maximum results

        Returns:
            List of messages ordered by scheduled_for DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM scheduled_messages
            WHERE customer_id = %s
            ORDER BY scheduled_for DESC
            LIMIT %s
            """,
            (customer_id, limit)
        )

        return [ScheduledMessage.model_validate(row) for row in rows]

    def process_pending(
        self,
        email_client,
        customer_email_lookup: Callable[[UUID], str | None]
    ) -> dict[str, int]:
        """
        Process all pending due messages, attempting to send each.

        Args:
            email_client: Email client with send(to, subject, body) method
            customer_email_lookup: Function to get email for customer_id

        Returns:
            Dict with counts: {"sent": N, "failed": N, "skipped": N}
        """
        pending = self.list_pending_due()
        results = {"sent": 0, "failed": 0, "skipped": 0}

        for message in pending:
            # Check preconditions
            email = customer_email_lookup(message.customer_id)
            if email is None:
                self.mark_skipped(message.id, "Customer has no email")
                results["skipped"] += 1
                continue

            # Attempt to send
            try:
                email_client.send(
                    to=email,
                    subject=message.subject or "",
                    body=message.body or ""
                )
                self.mark_sent(message.id)
                results["sent"] += 1
            except Exception as e:
                logger.error(f"Failed to send message {message.id}: {e}")
                self.mark_failed(message.id)
                results["failed"] += 1

        return results
