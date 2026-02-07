"""
Handler for InvoicePaid events.

On invoice payment, schedules a receipt/thank-you message to the customer.
"""

import logging
from typing import Callable

from core.events import InvoicePaid
from core.models import ScheduledMessageCreate, MessageType
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


def handle_invoice_paid(message_service) -> Callable:
    """
    Factory that returns an InvoicePaid handler.

    Args:
        message_service: MessageService instance

    Returns:
        Handler callable that schedules a receipt message
    """

    def handler(event: InvoicePaid):
        invoice = event.invoice

        message_service.schedule(ScheduledMessageCreate(
            customer_id=invoice.customer_id,
            message_type=MessageType.CUSTOM,
            subject="Payment received",
            body=f"Thank you! Payment received for invoice {invoice.invoice_number}.",
            scheduled_for=now_utc(),
        ))

    return handler
