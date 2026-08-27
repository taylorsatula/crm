"""
Handler for TicketCompleted events.

On ticket completion, extracts structured attributes from unprocessed
notes via LLM, persists them, and marks notes as processed.

`process_ticket_completed` is the synchronous, testable core. `handle_ticket_completed`
wraps it in a background daemon thread so it does not block the closeout response;
the thread swallows and logs exceptions so fire-and-forget callers never see them.
"""

import logging
import threading
from typing import Callable

from core.events import TicketCompleted

logger = logging.getLogger(__name__)


def process_ticket_completed(extractor, attribute_service, note_service) -> Callable:
    """
    Factory that returns the synchronous TicketCompleted processor.

    Processes unprocessed notes for the ticket: extracts attributes via the LLM
    extractor, persists them, and marks each note processed. Exceptions propagate
    so callers (and tests) see real failures.

    Args:
        extractor: AttributeExtractor instance
        attribute_service: AttributeService instance
        note_service: NoteService instance

    Returns:
        Synchronous callable taking a TicketCompleted event.
    """

    def process(event: TicketCompleted) -> None:
        ticket = event.ticket
        notes = note_service.list_unprocessed_for_ticket(ticket.id)

        if not notes:
            return

        for note in notes:
            extraction = extractor.extract_attributes(note.content)

            attribute_service.bulk_create_from_extraction(
                ticket.customer_id,
                extraction.attributes,
                note.id,
                extraction.confidence,
            )

            note_service.mark_processed(note.id)

    return process


def handle_ticket_completed(extractor, attribute_service, note_service) -> Callable:
    """
    Factory that returns the fire-and-forget TicketCompleted handler.

    Runs `process_ticket_completed` in a daemon thread; per-run failures are
    logged and swallowed so the closeout response is never blocked or broken.

    Args:
        extractor: AttributeExtractor instance
        attribute_service: AttributeService instance
        note_service: NoteService instance

    Returns:
        Handler callable that processes TicketCompleted events in the background.
    """
    process = process_ticket_completed(extractor, attribute_service, note_service)

    def handler(event: TicketCompleted) -> None:
        def _run() -> None:
            try:
                process(event)
            except Exception:
                logger.exception(
                    "Attribute extraction failed for ticket %s", event.ticket.id
                )

        threading.Thread(
            target=_run,
            daemon=True,
            name="attr-extract",
        ).start()

    return handler
