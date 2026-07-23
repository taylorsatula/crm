"""Transactional workflow for structured ticket closeout."""

from __future__ import annotations

from uuid import UUID, uuid4

from psycopg.types.json import Json

from clients.postgres_client import PostgresClient
from core.audit import AuditAction, AuditLogger
from core.exceptions import NotFoundError, TicketNotCloseableError
from core.models import (
    CloseoutRequest,
    Ticket,
    TicketCloseout,
)
from core.services.ticket_service import TicketService
from utils.timezone import now_utc
from utils.workspace_context import get_current_workspace_id


class TicketCloseoutService:
    """Persist one closeout aggregate and transition the ticket to completed."""

    def __init__(
        self,
        postgres: PostgresClient,
        audit: AuditLogger,
        ticket_service: TicketService,
    ) -> None:
        self.postgres = postgres
        self.audit = audit
        self.ticket_service = ticket_service

    def closeout(self, data: CloseoutRequest) -> dict:
        """Execute the closeout command as one transaction."""
        with self.postgres.transaction():
            ticket = self._load_open_ticket(data.ticket_id)
            self._record_actual_duration(ticket, data.actual_duration_minutes)
            closeout = self._create_closeout_record(ticket=ticket, data=data)
            closed_ticket = self.ticket_service.close(ticket.id)

        return {
            "ticket": closed_ticket.model_dump(mode="json"),
            "closeout": closeout.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------ reads

    def get_for_ticket(self, ticket_id: UUID) -> TicketCloseout | None:
        """Return the structured closeout aggregate for one ticket."""
        row = self.postgres.execute_single(
            "SELECT * FROM ticket_closeouts WHERE ticket_id = %s",
            (ticket_id,),
        )
        return TicketCloseout.model_validate(row) if row is not None else None

    # ------------------------------------------------------------- internals

    def _load_open_ticket(self, ticket_id: UUID) -> Ticket:
        """Lock one nonterminal ticket before closing it."""
        row = self.postgres.execute_single(
            """
            SELECT * FROM tickets
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (ticket_id,),
        )
        if row is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        ticket = Ticket.model_validate(row)
        if ticket.is_closed:
            raise TicketNotCloseableError(f"Ticket {ticket_id} already closed")
        return ticket

    def _record_actual_duration(self, ticket: Ticket, actual_duration_minutes: int) -> None:
        """Persist actual work time on the ticket."""
        self.postgres.execute(
            """
            UPDATE tickets
            SET actual_duration_minutes = %s, updated_at = %s
            WHERE id = %s
            """,
            (actual_duration_minutes, now_utc(), ticket.id),
        )

    def _create_closeout_record(
        self,
        *,
        ticket: Ticket,
        data: CloseoutRequest,
    ) -> TicketCloseout:
        """Persist the canonical closeout aggregate."""
        closeout_id = uuid4()
        now = now_utc()
        row = self.postgres.execute_returning(
            """
            INSERT INTO ticket_closeouts (
                id, workspace_id, ticket_id, actual_duration_minutes,
                quoted_scope_status, result_status, customer_response,
                next_service_disposition, next_service_note,
                technician_summary, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                closeout_id,
                get_current_workspace_id(),
                ticket.id,
                data.actual_duration_minutes,
                data.quoted_scope_status,
                data.result_status,
                data.customer_capture.customer_response,
                data.next_service.disposition,
                data.next_service.note,
                data.technician_summary,
                now,
            ),
        )[0]
        closeout = TicketCloseout.model_validate(row)
        self.audit.log_change(
            entity_type="ticket_closeout",
            entity_id=closeout.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json")},
        )
        return closeout
