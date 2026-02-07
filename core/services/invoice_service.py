"""
Invoice service for billing and payments.

Invoices are always created from tickets. They capture the ticket's line items
at a point in time for billing purposes.
"""

import logging
from datetime import datetime
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.event_bus import EventBus
from core.events import InvoiceSent, InvoicePaid
from core.models import Invoice, InvoiceStatus
from utils.user_context import get_current_user_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service for invoice operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger, event_bus: EventBus):
        self.postgres = postgres
        self.audit = audit
        self.event_bus = event_bus

    def _generate_invoice_number(self, user_id: UUID) -> str:
        """
        Generate a unique invoice number for a user.

        Format: INV-YYYYMMDD-XXXX where XXXX is a sequence number.
        """
        today = now_utc().strftime("%Y%m%d")
        prefix = f"INV-{today}-"

        # Find highest existing number for today
        result = self.postgres.execute_single(
            """
            SELECT invoice_number FROM invoices
            WHERE user_id = %s AND invoice_number LIKE %s
            ORDER BY invoice_number DESC
            LIMIT 1
            """,
            (user_id, f"{prefix}%")
        )

        if result is None:
            sequence = 1
        else:
            # Extract sequence number from existing invoice
            existing = result["invoice_number"]
            try:
                sequence = int(existing.split("-")[-1]) + 1
            except (ValueError, IndexError):
                sequence = 1

        return f"{prefix}{sequence:04d}"

    def create_from_ticket(
        self,
        ticket_id: UUID,
        tax_rate_bps: int = 0,
        notes: str | None = None,
        due_at: datetime | None = None
    ) -> Invoice:
        """
        Create an invoice from a ticket's line items.

        Args:
            ticket_id: Ticket to create invoice from
            tax_rate_bps: Tax rate in basis points (1000 = 10%)
            notes: Optional invoice notes
            due_at: Optional due date

        Returns:
            Created invoice in DRAFT status

        Raises:
            ValueError: If ticket not found or has no line items
        """
        user_id = get_current_user_id()

        # Get ticket and customer
        ticket = self.postgres.execute_single(
            "SELECT customer_id FROM tickets WHERE id = %s",
            (ticket_id,)
        )
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found")

        customer_id = ticket["customer_id"]

        # Sum line items
        result = self.postgres.execute_single(
            """
            SELECT COALESCE(SUM(total_price_cents), 0) as subtotal
            FROM line_items
            WHERE ticket_id = %s AND deleted_at IS NULL
            """,
            (ticket_id,)
        )

        subtotal_cents = result["subtotal"]
        if subtotal_cents == 0:
            raise ValueError(f"Ticket {ticket_id} has no line items")

        # Calculate tax and total
        tax_amount_cents = (subtotal_cents * tax_rate_bps) // 10000
        total_amount_cents = subtotal_cents + tax_amount_cents

        invoice_id = uuid4()
        invoice_number = self._generate_invoice_number(user_id)
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO invoices (
                id, user_id, customer_id, ticket_id,
                invoice_number, status,
                subtotal_cents, tax_rate_bps, tax_amount_cents, total_amount_cents,
                amount_paid_cents, notes, due_at,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            RETURNING *
            """,
            (
                invoice_id, user_id, customer_id, ticket_id,
                invoice_number, InvoiceStatus.DRAFT.value,
                subtotal_cents, tax_rate_bps, tax_amount_cents, total_amount_cents,
                0, notes, due_at,
                now, now
            )
        )[0]

        invoice = Invoice.model_validate(row)

        self.audit.log_change(
            entity_type="invoice",
            entity_id=invoice.id,
            action=AuditAction.CREATE,
            changes={
                "created": {
                    "ticket_id": str(ticket_id),
                    "subtotal_cents": subtotal_cents,
                    "tax_rate_bps": tax_rate_bps,
                    "total_amount_cents": total_amount_cents
                }
            }
        )

        return invoice

    def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        """
        Get invoice by ID.

        Args:
            invoice_id: Invoice UUID

        Returns:
            Invoice if found and not deleted, None otherwise.
        """
        row = self.postgres.execute_single(
            "SELECT * FROM invoices WHERE id = %s AND deleted_at IS NULL",
            (invoice_id,)
        )

        if row is None:
            return None

        return Invoice.model_validate(row)

    def send(self, invoice_id: UUID) -> Invoice:
        """
        Send an invoice.

        Args:
            invoice_id: Invoice UUID

        Returns:
            Updated invoice with SENT status

        Raises:
            ValueError: If invoice not found or already voided
        """
        current = self.get_by_id(invoice_id)
        if current is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        if current.status == InvoiceStatus.VOID:
            raise ValueError(f"Invoice {invoice_id} is voided")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE invoices
            SET status = %s, sent_at = %s, issued_at = COALESCE(issued_at, %s), updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (InvoiceStatus.SENT.value, now, now, now, invoice_id)
        )[0]

        updated = Invoice.model_validate(row)

        self.audit.log_change(
            entity_type="invoice",
            entity_id=invoice_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"old": current.status.value, "new": InvoiceStatus.SENT.value},
                "sent_at": {"old": None, "new": now.isoformat()}
            }
        )

        self.event_bus.publish(InvoiceSent.create(invoice=updated))

        return updated

    def record_payment(self, invoice_id: UUID, amount_cents: int) -> Invoice:
        """
        Record a payment on an invoice.

        Args:
            invoice_id: Invoice UUID
            amount_cents: Payment amount in cents

        Returns:
            Updated invoice (status may become PARTIAL or PAID)

        Raises:
            ValueError: If invoice not found or invalid state
        """
        current = self.get_by_id(invoice_id)
        if current is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        if current.status == InvoiceStatus.VOID:
            raise ValueError(f"Invoice {invoice_id} is voided")

        new_amount_paid = current.amount_paid_cents + amount_cents
        now = now_utc()

        # Determine new status
        if new_amount_paid >= current.total_amount_cents:
            new_status = InvoiceStatus.PAID
            paid_at = now
        else:
            new_status = InvoiceStatus.PARTIAL
            paid_at = current.paid_at

        row = self.postgres.execute_returning(
            """
            UPDATE invoices
            SET amount_paid_cents = %s, status = %s, paid_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (new_amount_paid, new_status.value, paid_at, now, invoice_id)
        )[0]

        updated = Invoice.model_validate(row)

        self.audit.log_change(
            entity_type="invoice",
            entity_id=invoice_id,
            action=AuditAction.UPDATE,
            changes={
                "amount_paid_cents": {"old": current.amount_paid_cents, "new": new_amount_paid},
                "status": {"old": current.status.value, "new": new_status.value},
                "payment_recorded": amount_cents
            }
        )

        if new_status == InvoiceStatus.PAID:
            self.event_bus.publish(InvoicePaid.create(invoice=updated))

        return updated

    def void(self, invoice_id: UUID) -> Invoice:
        """
        Void an invoice.

        Args:
            invoice_id: Invoice UUID

        Returns:
            Voided invoice

        Raises:
            ValueError: If invoice not found or already paid
        """
        current = self.get_by_id(invoice_id)
        if current is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        if current.status == InvoiceStatus.PAID:
            raise ValueError(f"Invoice {invoice_id} is paid and cannot be voided")

        now = now_utc()
        row = self.postgres.execute_returning(
            """
            UPDATE invoices
            SET status = %s, voided_at = %s, updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (InvoiceStatus.VOID.value, now, now, invoice_id)
        )[0]

        updated = Invoice.model_validate(row)

        self.audit.log_change(
            entity_type="invoice",
            entity_id=invoice_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"old": current.status.value, "new": InvoiceStatus.VOID.value},
                "voided_at": {"old": None, "new": now.isoformat()}
            }
        )

        return updated

    def list_for_customer(self, customer_id: UUID, limit: int = 50) -> list[Invoice]:
        """
        List invoices for a customer.

        Args:
            customer_id: Customer UUID
            limit: Maximum results

        Returns:
            List of invoices ordered by creation time DESC
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM invoices
            WHERE customer_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (customer_id, limit)
        )

        return [Invoice.model_validate(row) for row in rows]

    def list_unpaid(self, limit: int = 50) -> list[Invoice]:
        """
        List unpaid invoices (sent but not paid/voided).

        Args:
            limit: Maximum results

        Returns:
            List of unpaid invoices ordered by due date
        """
        rows = self.postgres.execute(
            """
            SELECT * FROM invoices
            WHERE status IN ('sent', 'partial')
              AND deleted_at IS NULL
            ORDER BY COALESCE(due_at, created_at) ASC
            LIMIT %s
            """,
            (limit,)
        )

        return [Invoice.model_validate(row) for row in rows]
