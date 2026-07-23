"""Schedule CRM-owned default messages from ticket lifecycle events."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Callable

from core.events import TicketCompleted, TicketCreated
from core.models import MessageType, ScheduledMessageCreate
from utils.timezone import now_utc


def _add_months(instant: datetime, months: int) -> datetime:
    """Return the same local calendar day after a whole-month interval."""
    month_index = instant.month - 1 + months
    year = instant.year + month_index // 12
    month = month_index % 12 + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


def handle_ticket_created_messages(message_service, workspace_settings_service) -> Callable:
    """Schedule confirmation and reminder messages from workspace defaults."""

    def handler(event: TicketCreated) -> None:
        ticket = event.ticket
        settings = workspace_settings_service.get()
        if settings.appointment_confirmation_enabled:
            message_service.schedule(
                ScheduledMessageCreate(
                    customer_id=ticket.customer_id,
                    ticket_id=ticket.id,
                    message_type=MessageType.APPOINTMENT_CONFIRMATION,
                    subject="Appointment confirmation",
                    body="Your appointment has been scheduled.",
                    scheduled_for=now_utc(),
                )
            )
        if settings.appointment_reminder_minutes is None:
            return
        reminder_at = ticket.scheduled_at - timedelta(
            minutes=settings.appointment_reminder_minutes
        )
        if reminder_at <= now_utc():
            return
        message_service.schedule(
            ScheduledMessageCreate(
                customer_id=ticket.customer_id,
                ticket_id=ticket.id,
                message_type=MessageType.APPOINTMENT_REMINDER,
                subject="Appointment reminder",
                body="This is a reminder about your upcoming appointment.",
                scheduled_for=reminder_at,
            )
        )

    return handler


def handle_ticket_completed_messages(message_service, workspace_settings_service) -> Callable:
    """Schedule configured service reminders after a completed ticket."""

    def handler(event: TicketCompleted) -> None:
        ticket = event.ticket
        settings = workspace_settings_service.get()
        months = {"six_months": 6, "one_year": 12}.get(settings.service_reminder_mode)
        if months is None:
            return
        completed_at = ticket.closed_at or now_utc()
        message_service.schedule(
            ScheduledMessageCreate(
                customer_id=ticket.customer_id,
                ticket_id=ticket.id,
                message_type=MessageType.SERVICE_REMINDER,
                subject="Service reminder",
                body="It may be time to schedule your next service appointment.",
                scheduled_for=_add_months(completed_at, months),
            )
        )

    return handler
