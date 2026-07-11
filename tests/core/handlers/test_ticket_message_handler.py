"""CRM workspace defaults drive ticket lifecycle messages."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from core.events import TicketCompleted, TicketCreated
from core.handlers.ticket_message_handler import (
    handle_ticket_completed_messages,
    handle_ticket_created_messages,
)
from core.models import MessageType
from utils.timezone import now_utc


class RecordingMessageService:
    def __init__(self) -> None:
        self.scheduled = []

    def schedule(self, data) -> None:
        self.scheduled.append(data)


class StaticWorkspaceSettings:
    def __init__(self, settings) -> None:
        self.settings = settings

    def get(self):
        return self.settings


def test_ticket_created_schedules_confirmation_and_reminder_from_workspace_defaults():
    message_service = RecordingMessageService()
    settings = StaticWorkspaceSettings(SimpleNamespace(
        appointment_confirmation_enabled=True,
        appointment_reminder_minutes=120,
    ))
    ticket = SimpleNamespace(
        id=uuid4(),
        customer_id=uuid4(),
        scheduled_at=now_utc() + timedelta(days=2),
    )

    handle_ticket_created_messages(message_service, settings)(TicketCreated(ticket=ticket))

    assert [message.message_type for message in message_service.scheduled] == [
        MessageType.APPOINTMENT_CONFIRMATION,
        MessageType.APPOINTMENT_REMINDER,
    ]
    assert message_service.scheduled[1].scheduled_for == ticket.scheduled_at - timedelta(hours=2)


def test_ticket_completed_schedules_only_configured_service_reminders():
    message_service = RecordingMessageService()
    settings = StaticWorkspaceSettings(SimpleNamespace(service_reminder_mode="six_months"))
    completed_at = now_utc()
    ticket = SimpleNamespace(id=uuid4(), customer_id=uuid4(), closed_at=completed_at)

    handle_ticket_completed_messages(message_service, settings)(TicketCompleted(ticket=ticket))

    assert len(message_service.scheduled) == 1
    reminder = message_service.scheduled[0]
    assert reminder.message_type is MessageType.SERVICE_REMINDER
    assert reminder.scheduled_for.month == (completed_at.month - 1 + 6) % 12 + 1


def test_ask_each_time_does_not_schedule_service_message():
    message_service = RecordingMessageService()
    settings = StaticWorkspaceSettings(SimpleNamespace(service_reminder_mode="ask_each_time"))
    ticket = SimpleNamespace(id=uuid4(), customer_id=uuid4(), closed_at=now_utc())

    handle_ticket_completed_messages(message_service, settings)(TicketCompleted(ticket=ticket))

    assert message_service.scheduled == []
