"""
Handler for TicketCancelled events.

On ticket cancellation, cancels all pending scheduled messages
for that ticket (reminders, confirmations, etc.).
"""

import logging
from typing import Callable

from core.events import TicketCancelled

logger = logging.getLogger(__name__)


def handle_ticket_cancelled(message_service) -> Callable:
    """
    Factory that returns a TicketCancelled handler.

    Args:
        message_service: MessageService instance

    Returns:
        Handler callable that cancels pending messages for the ticket
    """

    def handler(event: TicketCancelled):
        ticket = event.ticket
        pending = message_service.list_pending_for_ticket(ticket.id)

        for message in pending:
            message_service.cancel(message.id)

    return handler
