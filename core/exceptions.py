"""Typed domain exceptions that surface as semantic API error codes.

Services raise these instead of bare ``ValueError`` so ``api/errors.py`` can
emit the correct machine-readable error code and HTTP status to clients.

Inheritance: ``DomainError`` extends ``ValueError``. This keeps existing
``isinstance(exc, ValueError)`` callers and ``pytest.raises(ValueError)``
assertions matching (the suite asserts ``ValueError`` for many lifecycle
failures), while ``api/errors.py`` registers a more-specific ``DomainError``
handler that Starlette selects first via MRO walk — so typed exceptions
surface their semantic ``code``/``http_status`` rather than the generic
``INVALID_REQUEST``/400 that a bare ``ValueError`` would produce.

The generic ``ValueError`` path remains for input-validation failures that
have no dedicated code (mapped to ``INVALID_REQUEST``/400, or ``NOT_FOUND``/404
when the message contains "not found").

Design:
- Each subclass carries a ``code`` (matches an ``ErrorCodes`` member in
  ``api/base.py``) and an ``http_status``.
- State-violation lifecycles use HTTP 409 Conflict; "not found" uses 404;
  plain input validation stays 400.
- Handlers in ``api/actions.py`` raise these directly; service ``delete``
  methods return ``False`` for missing entities and the handler raises
  ``NotFoundError``.
"""

from __future__ import annotations

from typing import Optional


class DomainError(ValueError):
    """Base for typed domain failures. Carries an error code and HTTP status.

    Extends ``ValueError`` so existing ValueError catchers keep matching while
    a more-specific handler surfaces the semantic code.
    """

    code: str = "INVALID_REQUEST"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details

    def __str__(self) -> str:
        return super().__str__()


class NotFoundError(DomainError):
    """A referenced entity does not exist (or is hidden by user isolation)."""

    code = "NOT_FOUND"
    http_status = 404


class TicketImmutableError(DomainError):
    """A ticket is completed/cancelled and cannot be mutated via normal writes."""

    code = "TICKET_IMMUTABLE"
    http_status = 409


class TicketNotClockableError(DomainError):
    """A clock_in/clock_out was attempted from an invalid ticket state."""

    code = "TICKET_NOT_CLOCKABLE"
    http_status = 409


class TicketNotCloseableError(DomainError):
    """A close/closeout/cancel was attempted from an invalid ticket state."""

    code = "TICKET_NOT_CLOSEABLE"
    http_status = 409


class InvalidStatusTransitionError(DomainError):
    """A requested state transition is not allowed for the current status."""

    code = "INVALID_STATUS_TRANSITION"
    http_status = 409


class TicketScheduleUnavailableError(DomainError):
    """A requested appointment falls outside the configured booking window."""

    code = "TICKET_SCHEDULE_UNAVAILABLE"
    http_status = 409


class TicketScheduleConflictError(DomainError):
    """A requested appointment overlaps another appointment or its travel buffer."""

    code = "TICKET_SCHEDULE_CONFLICT"
    http_status = 409


class InvoiceAlreadyPaidError(DomainError):
    """An operation (e.g. void) is blocked because the invoice is fully paid."""

    code = "INVOICE_ALREADY_PAID"
    http_status = 409


class AddressInUseError(DomainError):
    """An address cannot be deleted because one or more tickets reference it."""

    code = "ADDRESS_IN_USE"
    http_status = 409
