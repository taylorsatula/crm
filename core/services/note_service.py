"""
Note service for notes on customers and tickets.

Notes are free-form text that can be attached to either a customer or a ticket.
They can be processed by LLM to extract structured attributes.
"""

import logging
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction
from core.models import Note, NoteCreate
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


class NoteService:
    """Service for note operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    def create(self, data: NoteCreate) -> Note:
        """
        Create a new note.

        Args:
            data: Note creation data (must have exactly one parent)

        Returns:
            Created note
        """
        user_id = get_current_user_id()
        note_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO notes (
                id, user_id, customer_id, ticket_id,
                content, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                note_id, user_id, data.customer_id, data.ticket_id,
                data.content, now
            )
        )[0]

        note = Note.model_validate(row)

        self.audit.log_change(
            entity_type="note",
            entity_id=note.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)}
        )

        return note

    def get_by_id(self, note_id: UUID) -> Note | None:
        """
        Get note by ID.

        Args:
            note_id: Note UUID

        Returns:
            Note if found and not deleted, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM notes WHERE id = %s AND deleted_at IS NULL",
            (note_id,)
        )

        if row is None:
            return None

        return Note.model_validate(row)

    def list_for_customer(self, customer_id: UUID, limit: int = 50) -> list[Note]:
        """
        List all notes for a customer.

        Args:
            customer_id: Customer UUID
            limit: Maximum results

        Returns:
            List of notes ordered by creation time DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM notes
            WHERE customer_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (customer_id, limit)
        )

        return [Note.model_validate(row) for row in rows]

    def list_for_ticket(self, ticket_id: UUID, limit: int = 50) -> list[Note]:
        """
        List all notes for a ticket.

        Args:
            ticket_id: Ticket UUID
            limit: Maximum results

        Returns:
            List of notes ordered by creation time DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM notes
            WHERE ticket_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (ticket_id, limit)
        )

        return [Note.model_validate(row) for row in rows]

    def delete(self, note_id: UUID) -> bool:
        """
        Soft delete a note.

        Args:
            note_id: Note UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(note_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE notes
            SET deleted_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now_utc(), note_id)
        )

        self.audit.log_change(
            entity_type="note",
            entity_id=note_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True

    def mark_processed(self, note_id: UUID) -> Note:
        """
        Mark a note as processed by LLM extraction.

        Args:
            note_id: Note UUID

        Returns:
            Updated note with processed_at set

        Raises:
            ValueError: If note not found
        """
        current = self.get_by_id(note_id)
        if current is None:
            raise ValueError(f"Note {note_id} not found")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE notes
            SET processed_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (now, note_id)
        )[0]

        return Note.model_validate(row)

    def list_unprocessed(self, limit: int = 50) -> list[Note]:
        """
        List notes that haven't been processed by LLM.

        Args:
            limit: Maximum results

        Returns:
            List of unprocessed notes ordered by creation time ASC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM notes
            WHERE processed_at IS NULL AND deleted_at IS NULL
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,)
        )

        return [Note.model_validate(row) for row in rows]
