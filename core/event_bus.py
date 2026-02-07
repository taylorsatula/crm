"""
Event bus for CRM domain events.

Synchronous in-process pub/sub. Handlers execute immediately in the same
thread as the publisher. Handler errors are logged but never propagate —
the primary operation (DB write + audit) has already committed.
"""

import logging
from typing import Callable, Dict, List

from core.events import CRMEvent

logger = logging.getLogger(__name__)


class EventBus:
    """
    In-process event bus for CRM domain events.

    Subscribe by event class name (string), publish by event instance.
    Handlers are called synchronously in subscription order.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """
        Subscribe to events of a specific type.

        Args:
            event_type: Name of event class to subscribe to (e.g. 'TicketCompleted')
            callback: Function to call when event is published
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event: CRMEvent):
        """
        Publish an event to all subscribers of that type.

        Handlers are called synchronously in subscription order.
        Handler errors are logged but do not propagate — the primary
        operation has already committed.

        Args:
            event: CRMEvent instance to publish
        """
        event_type = event.__class__.__name__

        if event_type not in self._subscribers:
            return

        for callback in self._subscribers[event_type]:
            try:
                callback(event)
            except Exception:
                logger.exception(
                    "Handler %s failed for %s (event_id=%s)",
                    callback.__name__,
                    event_type,
                    event.event_id,
                )
