"""
Handler for TicketCompleted events.

On ticket completion, extracts structured attributes from unprocessed
notes via LLM, persists them, and marks notes as processed.
"""

import logging
from typing import Callable

from core.events import TicketCompleted

logger = logging.getLogger(__name__)


def handle_ticket_completed(extractor, attribute_service, note_service) -> Callable:
    """
    Factory that returns a TicketCompleted handler.

    Dependencies are captured at wiring time via closure.

    Args:
        extractor: AttributeExtractor instance
        attribute_service: AttributeService instance
        note_service: NoteService instance

    Returns:
        Handler callable that processes TicketCompleted events
    """

    def handler(event: TicketCompleted):
        ticket = event.ticket
        notes = note_service.list_unprocessed_for_ticket(ticket.id)

        for note in notes:
            extraction = extractor.extract_attributes(note.content)

            attribute_service.bulk_create_from_extraction(
                ticket.customer_id,
                extraction.attributes,
                note.id,
                extraction.confidence,
            )

            note_service.mark_processed(note.id)

    return handler
