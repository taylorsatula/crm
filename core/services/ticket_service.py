"""
Ticket service for appointment/job lifecycle.

Handles the full ticket lifecycle: create, clock in/out, close, cancel.
Tickets are immutable after being closed.
"""

import logging
from datetime import datetime, time, timezone, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.event_bus import EventBus
from core.events import TicketCreated, TicketClockIn, TicketCompleted, TicketCancelled
from core.exceptions import (
    NotFoundError,
    TicketImmutableError,
    TicketNotClockableError,
    TicketNotCloseableError,
    InvalidStatusTransitionError,
    TicketScheduleConflictError,
    TicketScheduleUnavailableError,
)
from core.models import Ticket, TicketCreate, TicketUpdate, TicketStatus, ConfirmationStatus
from core.services.workspace_settings_service import WorkspaceSettingsService
from utils.workspace_context import get_current_workspace_id, get_current_workspace_timezone
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

_UPDATABLE_COLUMNS = {
    "address_id", "scheduled_at", "scheduled_duration_minutes",
    "is_price_estimated", "notes", "confirmation_status"
}
# NOTE: `address_id` is updatable here (moving a job to a different service
# address is a valid backend operation), but the mira-OSS crm_jobs_tool layer
# deliberately does NOT expose it on update_ticket. Changing a job's address is
# intentionally handled by cancelling and recreating the ticket from the tool
# surface. Do not add address_id to the tool's update_ticket without an
# explicit decision — it is kept out of the tool contract on purpose.


class TicketService:
    """Service for ticket operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger, event_bus: EventBus):
        self.postgres = postgres
        self.audit = audit
        self.event_bus = event_bus

    def _validate_schedule(
        self,
        *,
        scheduled_at: datetime,
        duration_minutes: int,
        excluding_ticket_id: UUID | None = None,
    ) -> None:
        """Enforce the active workspace's workday, buffer, and booking rules."""
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")

        workspace_id = get_current_workspace_id()
        settings = WorkspaceSettingsService(self.postgres).get()
        timezone_name = get_current_workspace_timezone()
        local_start = scheduled_at.astimezone(ZoneInfo(timezone_name))
        weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[local_start.weekday()]
        local_end = local_start + timedelta(minutes=duration_minutes)
        buffered_end = local_start + timedelta(
            minutes=duration_minutes + settings.travel_buffer_minutes
        )
        schedule_details: dict[str, object] = {
            "timezone": timezone_name,
            "working_days": list(settings.working_days),
            "workday_start": settings.workday_start.isoformat(),
            "workday_end": settings.workday_end.isoformat(),
            "travel_buffer_minutes": settings.travel_buffer_minutes,
            "requested_start": local_start.isoformat(),
            "requested_end": local_end.isoformat(),
            "requested_buffered_end": buffered_end.isoformat(),
            "duration_minutes": duration_minutes,
        }

        if weekday not in settings.working_days:
            raise TicketScheduleUnavailableError(
                f"Appointments cannot be scheduled on {weekday}; configured working days are "
                f"{', '.join(settings.working_days)}",
                details={**schedule_details, "reason": "non_working_day"},
            )
        if (
            local_start.time() < settings.workday_start
            or buffered_end.date() != local_start.date()
            or buffered_end.time() > settings.workday_end
        ):
            raise TicketScheduleUnavailableError(
                "Appointment and travel buffer must fit inside the configured "
                f"{settings.workday_start.isoformat()}-{settings.workday_end.isoformat()} workday",
                details={**schedule_details, "reason": "outside_workday"},
            )

        query = """
            SELECT id, scheduled_at, scheduled_duration_minutes
            FROM tickets
            WHERE workspace_id = %s
              AND deleted_at IS NULL
              AND status IN ('scheduled', 'in_progress')
              AND scheduled_at < %s
              AND scheduled_at
                    + (COALESCE(scheduled_duration_minutes, %s) + %s) * INTERVAL '1 minute'
                    > %s
        """
        params: list[object] = [
            workspace_id,
            scheduled_at + timedelta(minutes=duration_minutes + settings.travel_buffer_minutes),
            settings.default_appointment_minutes,
            settings.travel_buffer_minutes,
            scheduled_at,
        ]
        if excluding_ticket_id is not None:
            query += " AND id <> %s"
            params.append(excluding_ticket_id)
        query += " LIMIT 1"
        conflict = self.postgres.execute_single(query, tuple(params))
        if conflict is not None:
            conflict_start = conflict["scheduled_at"].astimezone(local_start.tzinfo)
            conflict_duration = (
                conflict["scheduled_duration_minutes"]
                if conflict["scheduled_duration_minutes"] is not None
                else settings.default_appointment_minutes
            )
            conflict_end = conflict_start + timedelta(minutes=conflict_duration)
            conflict_buffered_end = conflict_end + timedelta(
                minutes=settings.travel_buffer_minutes
            )
            raise TicketScheduleConflictError(
                "Appointment conflicts with ticket "
                f"{conflict['id']} from {conflict_start.isoformat()} through "
                f"{conflict_buffered_end.isoformat()} including travel buffer",
                details={
                    **schedule_details,
                    "reason": "schedule_conflict",
                    "conflicting_ticket_id": str(conflict["id"]),
                    "conflicting_start": conflict_start.isoformat(),
                    "conflicting_end": conflict_end.isoformat(),
                    "conflicting_buffered_end": conflict_buffered_end.isoformat(),
                },
            )

    def create(self, data: TicketCreate) -> Ticket:
        """
        Create a new ticket.

        Args:
            data: Ticket creation data

        Returns:
            Created ticket in SCHEDULED status
        """
        workspace_id = get_current_workspace_id()
        ticket_id = uuid4()
        now = now_utc()
        settings = WorkspaceSettingsService(self.postgres).get()
        duration_minutes = (
            data.scheduled_duration_minutes
            if data.scheduled_duration_minutes is not None
            else settings.default_appointment_minutes
        )
        self._validate_schedule(
            scheduled_at=data.scheduled_at,
            duration_minutes=duration_minutes,
        )

        row = self.postgres.execute_returning(
            """
            INSERT INTO tickets (
                id, workspace_id, customer_id, address_id,
                status, scheduled_at, scheduled_duration_minutes,
                confirmation_status, is_price_estimated, notes,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                ticket_id, workspace_id, data.customer_id, data.address_id,
                TicketStatus.SCHEDULED.value, data.scheduled_at, duration_minutes,
                ConfirmationStatus.PENDING.value, data.is_price_estimated, data.notes,
                now, now
            )
        )[0]

        ticket = Ticket.model_validate(row)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket.id,
            action=AuditAction.CREATE,
            changes={
                "created": {
                    **data.model_dump(mode="json", exclude_none=True),
                    "scheduled_duration_minutes": duration_minutes,
                }
            }
        )

        self.event_bus.publish(TicketCreated.create(ticket=ticket))

        return ticket

    def get_by_id(self, ticket_id: UUID) -> Ticket | None:
        """
        Get ticket by ID.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Ticket if found, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM tickets WHERE id = %s AND deleted_at IS NULL",
            (ticket_id,)
        )

        if row is None:
            return None

        return Ticket.model_validate(row)

    def update(self, ticket_id: UUID, data: TicketUpdate) -> Ticket:
        """
        Update ticket fields.

        Args:
            ticket_id: Ticket UUID
            data: Fields to update

        Returns:
            Updated ticket

        Raises:
            ValueError: If ticket not found or is closed
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")

        if current.is_closed:
            raise TicketImmutableError(f"Ticket {ticket_id} is closed and immutable")

        updates = data.model_dump(exclude_none=True)
        if not updates:
            return current

        for field in updates:
            if field not in _UPDATABLE_COLUMNS:
                logger.warning(
                    f"Attempted to update unknown field '{field}' on ticket {ticket_id}"
                )

        # Convert enums to strings
        if "confirmation_status" in updates and hasattr(updates["confirmation_status"], "value"):
            updates["confirmation_status"] = updates["confirmation_status"].value

        valid_updates = {k: v for k, v in updates.items() if k in _UPDATABLE_COLUMNS}
        if not valid_updates:
            return current

        if "scheduled_at" in valid_updates or "scheduled_duration_minutes" in valid_updates:
            self._validate_schedule(
                scheduled_at=valid_updates.get("scheduled_at", current.scheduled_at),
                duration_minutes=valid_updates.get(
                    "scheduled_duration_minutes",
                    current.scheduled_duration_minutes
                    or WorkspaceSettingsService(self.postgres).get().default_appointment_minutes,
                ),
                excluding_ticket_id=ticket_id,
            )

        set_parts = []
        params = []
        for field, value in valid_updates.items():
            set_parts.append(f"{field} = %s")
            params.append(value)

        set_parts.append("updated_at = %s")
        params.append(now_utc())
        params.append(ticket_id)

        row = self.postgres.execute_returning(
            f"""
            UPDATE tickets
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(params)
        )[0]

        updated = Ticket.model_validate(row)

        changes = compute_changes(
            current.model_dump(mode="json"),
            updated.model_dump(mode="json")
        )
        if changes:
            self.audit.log_change(
                entity_type="ticket",
                entity_id=ticket_id,
                action=AuditAction.UPDATE,
                changes=changes
            )

        return updated

    def clock_in(self, ticket_id: UUID) -> Ticket:
        """
        Clock in to start working on ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Updated ticket with clock_in_at set

        Raises:
            ValueError: If ticket not in valid state for clock in
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")

        # Check clock_in_at first - more specific error
        if current.clock_in_at is not None:
            raise TicketNotClockableError(f"Ticket {ticket_id} already clocked in")

        if current.status != TicketStatus.SCHEDULED:
            raise TicketNotClockableError(f"Ticket {ticket_id} cannot clock in - status is {current.status.value}")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE tickets
            SET clock_in_at = %s, status = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (now, TicketStatus.IN_PROGRESS.value, now, ticket_id)
        )[0]

        updated = Ticket.model_validate(row)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "clock_in_at": {"old": None, "new": now.isoformat()},
                "status": {"old": current.status.value, "new": TicketStatus.IN_PROGRESS.value}
            }
        )

        self.event_bus.publish(TicketClockIn.create(ticket=updated))

        return updated

    def clock_out(self, ticket_id: UUID) -> Ticket:
        """
        Clock out after finishing work on ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Updated ticket with clock_out_at and duration set

        Raises:
            ValueError: If ticket not clocked in
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")

        if current.clock_in_at is None:
            raise TicketNotClockableError(f"Ticket {ticket_id} not clocked in")

        if current.clock_out_at is not None:
            raise TicketNotClockableError(f"Ticket {ticket_id} already clocked out")

        now = now_utc()
        duration_minutes = int((now - current.clock_in_at).total_seconds() / 60)

        row = self.postgres.execute_returning(
            """
            UPDATE tickets
            SET clock_out_at = %s, actual_duration_minutes = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (now, duration_minutes, now, ticket_id)
        )[0]

        updated = Ticket.model_validate(row)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "clock_out_at": {"old": None, "new": now.isoformat()},
                "actual_duration_minutes": {"old": None, "new": duration_minutes}
            }
        )

        return updated

    def close(self, ticket_id: UUID) -> Ticket:
        """
        Close ticket after completion.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Closed ticket

        Raises:
            ValueError: If ticket cannot be closed
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")

        if current.is_closed:
            raise TicketNotCloseableError(f"Ticket {ticket_id} already closed")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE tickets
            SET closed_at = %s, status = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (now, TicketStatus.COMPLETED.value, now, ticket_id)
        )[0]

        updated = Ticket.model_validate(row)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "closed_at": {"old": None, "new": now.isoformat()},
                "status": {"old": current.status.value, "new": TicketStatus.COMPLETED.value}
            }
        )

        self.event_bus.publish(TicketCompleted.create(ticket=updated))

        return updated

    def cancel(self, ticket_id: UUID) -> Ticket:
        """
        Cancel a ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Cancelled ticket

        Raises:
            ValueError: If ticket cannot be cancelled
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")

        if current.status == TicketStatus.COMPLETED:
            raise InvalidStatusTransitionError(f"Ticket {ticket_id} cannot cancel - already completed")

        if current.status == TicketStatus.CANCELLED:
            raise InvalidStatusTransitionError(f"Ticket {ticket_id} already cancelled")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE tickets
            SET status = %s, closed_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (TicketStatus.CANCELLED.value, now, now, ticket_id)
        )[0]

        updated = Ticket.model_validate(row)

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"old": current.status.value, "new": TicketStatus.CANCELLED.value},
                "closed_at": {"old": None, "new": now.isoformat()}
            }
        )

        self.event_bus.publish(TicketCancelled.create(ticket=updated))

        return updated

    def list_by_date_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> list[Ticket]:
        """
        List tickets scheduled within a date range.

        Args:
            start: Start of range (inclusive)
            end: End of range (inclusive)
            limit: Maximum results

        Returns:
            List of tickets ordered by scheduled_at
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM tickets
            WHERE scheduled_at >= %s AND scheduled_at <= %s
              AND deleted_at IS NULL
            ORDER BY scheduled_at ASC
            LIMIT %s
            """,
            (start, end, limit)
        )

        return [Ticket.model_validate(row) for row in rows]

    def list_today(self) -> list[Ticket]:
        """
        List tickets scheduled for the authenticated workspace's local today.

        The caller supplies a validated IANA timezone in
        ``X-Workspace-Timezone``. Day boundaries are computed in that timezone
        and converted to UTC for the query, so a late-evening local job is not
        pushed into the adjacent UTC day.

        Returns:
            List of tickets scheduled for the workspace's local today, ordered by
            scheduled_at ASC
        """
        local_tz = ZoneInfo(get_current_workspace_timezone())

        now_local = now_utc().astimezone(local_tz)
        today_local_start = datetime.combine(now_local.date(), time.min, tzinfo=local_tz)
        tomorrow_local_start = today_local_start + timedelta(days=1)

        # scheduled_at is stored as TIMESTAMPTZ (UTC); compare against the
        # local-day boundaries expressed in UTC.
        start_utc = today_local_start.astimezone(timezone.utc)
        end_utc = tomorrow_local_start.astimezone(timezone.utc)

        rows = self.postgres.execute(
            """
            SELECT * FROM tickets
            WHERE scheduled_at >= %s AND scheduled_at < %s
              AND deleted_at IS NULL
            ORDER BY scheduled_at ASC
            """,
            (start_utc, end_utc)
        )

        return [Ticket.model_validate(row) for row in rows]

    def list_upcoming(self, limit: int = 50) -> list[Ticket]:
        """
        List upcoming active tickets.

        Args:
            limit: Maximum results

        Returns:
            Future scheduled or in-progress tickets ordered by scheduled_at ASC.
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM tickets
            WHERE deleted_at IS NULL
              AND (
                (status = %s AND scheduled_at >= %s)
                OR status = %s
              )
            ORDER BY scheduled_at ASC
            LIMIT %s
            """,
            (TicketStatus.SCHEDULED.value, now_utc(), TicketStatus.IN_PROGRESS.value, limit)
        )

        return [Ticket.model_validate(row) for row in rows]

    def list_all(self, limit: int = 50) -> list[Ticket]:
        """
        List all non-deleted tickets.

        Args:
            limit: Maximum results

        Returns:
            Tickets ordered by scheduled_at DESC.
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM tickets
            WHERE deleted_at IS NULL
            ORDER BY scheduled_at DESC
            LIMIT %s
            """,
            (limit,)
        )

        return [Ticket.model_validate(row) for row in rows]

    def get_current(self) -> Ticket | None:
        """
        Get the currently in-progress ticket.

        Returns:
            In-progress ticket or None if no ticket is being worked on.
        """
        row = self.postgres.execute_single(
            """
            SELECT * FROM tickets
            WHERE status = %s
              AND clock_in_at IS NOT NULL
              AND clock_out_at IS NULL
              AND deleted_at IS NULL
            ORDER BY clock_in_at DESC
            LIMIT 1
            """,
            (TicketStatus.IN_PROGRESS.value,)
        )

        if row is None:
            return None

        return Ticket.model_validate(row)

    def list_for_customer(self, customer_id: UUID, limit: int = 50) -> list[Ticket]:
        """
        List tickets for a customer.

        Args:
            customer_id: Customer UUID
            limit: Maximum results

        Returns:
            List of tickets ordered by scheduled_at DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM tickets
            WHERE customer_id = %s
              AND deleted_at IS NULL
            ORDER BY scheduled_at DESC
            LIMIT %s
            """,
            (customer_id, limit)
        )

        return [Ticket.model_validate(row) for row in rows]

    def delete(self, ticket_id: UUID) -> bool:
        """
        Soft delete a ticket.

        Args:
            ticket_id: Ticket UUID

        Returns:
            True if deleted, False if not found
        """
        current = self.get_by_id(ticket_id)
        if current is None:
            return False

        self.postgres.execute_returning(
            """
            UPDATE tickets
            SET deleted_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now_utc(), now_utc(), ticket_id)
        )

        self.audit.log_change(
            entity_type="ticket",
            entity_id=ticket_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")}
        )

        return True
