"""
Quote service for CRM quoting pipeline.

Owns the quote entity: create, read, update, status transitions (draft → sent →
accepted | rejected | expired | archived), line-item management, and acceptance
which links to a ticket.

Quotes reference a customer, optional lead, and contain line items (services,
quantities, prices). When accepted the caller is responsible for creating the
corresponding ticket — this service only stamps `created_ticket_id` and
`accepted_at`.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from core.audit import AuditLogger, AuditAction, compute_changes
from core.exceptions import NotFoundError, QuoteInvalidTransitionError, QuoteNotFoundError
from core.models import (
    Quote, QuoteCreate, QuoteUpdate, QuoteStatus, QUOTE_VALID_TRANSITIONS,
    QuoteLineItem, QuoteLineItemCreate, QuoteLineItemUpdate,
)

from utils.workspace_context import get_current_workspace_id
from utils.timezone import now_utc

logger = logging.getLogger(__name__)

_QUOTE_UPDATABLE_FIELDS = {"title", "notes", "expires_at"}
_LI_UPDATABLE_FIELDS = {
    "service_id", "description", "quantity",
    "unit_price_cents", "total_price_cents", "duration_minutes", "notes",
}


@dataclass(frozen=True)
class QuotePage:
    quotes: list[Quote]
    next_cursor: str | None


class QuoteService:
    """Service for quote and quote-line-item operations."""

    def __init__(self, postgres: PostgresClient, audit: AuditLogger):
        self.postgres = postgres
        self.audit = audit

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    def create(self, data: QuoteCreate) -> Quote:
        """Create a quote in 'draft' status."""
        workspace_id = get_current_workspace_id()
        quote_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO quotes (
                id, workspace_id, customer_id, status, title, notes, expires_at,
                lead_id, created_at, updated_at
            ) VALUES (
                %s, %s, %s, 'draft', %s, %s, %s,
                %s, %s, %s
            )
            RETURNING *
            """,
            (
                quote_id, workspace_id, data.customer_id,
                data.title, data.notes, data.expires_at,
                data.lead_id, now, now,
            ),
        )[0]

        quote = Quote.model_validate(row)
        self.audit.log_change(
            entity_type="quote",
            entity_id=quote.id,
            action=AuditAction.CREATE,
            changes={"created": data.model_dump(mode="json", exclude_none=True)},
        )
        return quote

    def get_by_id(self, quote_id: UUID) -> Quote | None:
        """Fetch one quote by id, scoped by RLS, not soft-deleted."""
        row = self.postgres.execute_single(
            "SELECT * FROM quotes WHERE id = %s AND deleted_at IS NULL",
            (quote_id,),
        )
        if row is None:
            return None
        return Quote.model_validate(row)

    def update(self, quote_id: UUID, data: QuoteUpdate) -> Quote:
        """Update title/notes/expires_at on a draft quote."""
        current = self.get_by_id(quote_id)
        if current is None:
            raise QuoteNotFoundError(f"Quote {quote_id} not found")
        if current.status != QuoteStatus.DRAFT:
            raise QuoteInvalidTransitionError(
                f"Quote {quote_id} is '{current.status.value}'; only draft quotes can be edited"
            )

        updates = {k: v for k, v in data.model_dump(exclude_none=True).items() if k in _QUOTE_UPDATABLE_FIELDS}
        if not updates:
            return current

        set_parts = []
        params: list = []
        for field, value in updates.items():
            set_parts.append(f"{field} = %s")
            params.append(value)
        set_parts.append("updated_at = %s")
        params.append(now_utc())
        params.append(quote_id)

        row = self.postgres.execute_returning(
            f"UPDATE quotes SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
            tuple(params),
        )[0]

        updated = Quote.model_validate(row)
        changes = compute_changes(current.model_dump(mode="json"), updated.model_dump(mode="json"))
        if changes:
            self.audit.log_change(
                entity_type="quote",
                entity_id=quote_id,
                action=AuditAction.UPDATE,
                changes=changes,
            )
        return updated

    def transition(self, quote_id: UUID, target_status: str) -> Quote:
        """
        Execute a quote status transition. Stamps the corresponding timestamp.

        - sent     → sets sent_at
        - accepted → requires created_ticket_id (stamp accepted_at)
        - rejected → sets rejected_at
        - expired/archived → sets archived_at
        """
        current = self.get_by_id(quote_id)
        if current is None:
            raise QuoteNotFoundError(f"Quote {quote_id} not found")

        current_str = current.status.value
        allowed = QUOTE_VALID_TRANSITIONS.get(current_str, set())
        if target_status not in allowed:
            raise QuoteInvalidTransitionError(
                f"Invalid quote transition '{current_str}' → '{target_status}'. "
                f"Allowed: {', '.join(sorted(allowed)) or '(none)'}"
            )

        now = now_utc()
        ts_col = {
            "sent": "sent_at",
            "accepted": "accepted_at",
            "rejected": "rejected_at",
            "expired": "archived_at",
            "archived": "archived_at",
        }.get(target_status)

        if target_status == "accepted":
            raise QuoteInvalidTransitionError(
                "Use accept_quote() which also requires created_ticket_id"
            )

        if ts_col:
            self.postgres.execute(
                f"UPDATE quotes SET status = %s, {ts_col} = %s, updated_at = %s WHERE id = %s",
                (target_status, now, now, quote_id),
            )
        else:
            self.postgres.execute(
                "UPDATE quotes SET status = %s, updated_at = %s WHERE id = %s",
                (target_status, now, quote_id),
            )

        self.audit.log_change(
            entity_type="quote",
            entity_id=quote_id,
            action=AuditAction.UPDATE,
            changes={"status": {"from": current_str, "to": target_status}},
        )
        return self.get_by_id(quote_id)

    def accept(self, quote_id: UUID, created_ticket_id: UUID) -> Quote:
        """
        Accept a quote: sets status=accepted, accepted_at, and links to the
        ticket that was created from this quote's scope.
        """
        current = self.get_by_id(quote_id)
        if current is None:
            raise QuoteNotFoundError(f"Quote {quote_id} not found")
        if current.status != QuoteStatus.SENT:
            raise QuoteInvalidTransitionError(
                f"Quote {quote_id} must be 'sent' to accept; current status is "
                f"'{current.status.value}'"
            )

        now = now_utc()
        self.postgres.execute(
            """
            UPDATE quotes
            SET status = 'accepted', accepted_at = %s, created_ticket_id = %s, updated_at = %s
            WHERE id = %s
            """,
            (now, created_ticket_id, now, quote_id),
        )

        self.audit.log_change(
            entity_type="quote",
            entity_id=quote_id,
            action=AuditAction.UPDATE,
            changes={
                "status": {"from": "sent", "to": "accepted"},
                "created_ticket_id": str(created_ticket_id),
            },
        )
        return self.get_by_id(quote_id)

    def delete(self, quote_id: UUID) -> bool:
        """Soft delete a quote. Also soft-deletes its line items."""
        current = self.get_by_id(quote_id)
        if current is None:
            return False

        now = now_utc()
        self.postgres.execute(
            "UPDATE quotes SET deleted_at = %s, updated_at = %s WHERE id = %s",
            (now, now, quote_id),
        )
        self.postgres.execute(
            "UPDATE quote_line_items SET deleted_at = %s, updated_at = %s WHERE quote_id = %s AND deleted_at IS NULL",
            (now, now, quote_id),
        )

        self.audit.log_change(
            entity_type="quote",
            entity_id=quote_id,
            action=AuditAction.DELETE,
            changes={"deleted": current.model_dump(mode="json")},
        )
        return True

    def list_page(
        self,
        customer_id: UUID | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> QuotePage:
        """Cursor-paginated quote listing ordered by (created_at DESC, id DESC)."""
        if limit < 1:
            raise ValueError("Quote page limit must be positive")

        conditions = ["deleted_at IS NULL"]
        params: list = []

        if customer_id is not None:
            conditions.append("customer_id = %s")
            params.append(customer_id)
        if status:
            conditions.append("status = %s")
            params.append(status)

        if cursor is not None:
            from core.services.customer_service import _decode_customer_cursor
            created_at, id_ = _decode_customer_cursor(cursor)
            conditions.append("(created_at, id) < (%s, %s)")
            params.extend([created_at, id_])

        params.append(limit + 1)
        rows = self.postgres.execute(
            f"""
            SELECT * FROM quotes
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        quotes = [Quote.model_validate(row) for row in rows]
        has_more = len(quotes) > limit
        selected = quotes[:limit]
        next_cursor = None
        if has_more and selected:
            from core.services.customer_service import _encode_customer_cursor
            next_cursor = _encode_customer_cursor(selected[-1].created_at, selected[-1].id)
        return QuotePage(quotes=selected, next_cursor=next_cursor)

    # ------------------------------------------------------------------
    # Quote Line Items
    # ------------------------------------------------------------------

    def create_line_item(self, quote_id: UUID, data: QuoteLineItemCreate) -> QuoteLineItem:
        """Add a line item to a draft quote."""
        current = self.get_by_id(quote_id)
        if current is None:
            raise QuoteNotFoundError(f"Quote {quote_id} not found")
        if current.status != QuoteStatus.DRAFT:
            raise QuoteInvalidTransitionError(
                f"Quote {quote_id} is '{current.status.value}'; "
                "line items can only be modified on draft quotes"
            )

        workspace_id = get_current_workspace_id()
        li_id = uuid4()
        now = now_utc()

        row = self.postgres.execute_returning(
            """
            INSERT INTO quote_line_items (
                id, workspace_id, quote_id, service_id,
                description, quantity, unit_price_cents, total_price_cents,
                duration_minutes, notes, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                li_id, workspace_id, quote_id, data.service_id,
                data.description, data.quantity, data.unit_price_cents, data.total_price_cents,
                data.duration_minutes, data.notes, now, now,
            ),
        )[0]

        li = QuoteLineItem.model_validate(row)
        self.audit.log_change(
            entity_type="quote_line_item",
            entity_id=li.id,
            action=AuditAction.CREATE,
            changes={
                "created": {
                    "quote_id": str(quote_id),
                    **data.model_dump(mode="json", exclude_none=True),
                }
            },
        )
        return li

    def list_line_items(self, quote_id: UUID) -> list[QuoteLineItem]:
        """Get all non-deleted line items for a quote."""
        rows = self.postgres.execute(
            """
            SELECT * FROM quote_line_items
            WHERE quote_id = %s AND deleted_at IS NULL
            ORDER BY created_at
            """,
            (quote_id,),
        )
        return [QuoteLineItem.model_validate(row) for row in rows]

    def update_line_item(self, li_id: UUID, data: QuoteLineItemUpdate) -> QuoteLineItem:
        """Update a line item on a draft quote."""
        current_li = self._get_line_item_by_id(li_id)
        if current_li is None:
            raise NotFoundError(f"Quote line item {li_id} not found")

        parent = self.get_by_id(current_li.quote_id)
        if parent is None or parent.status != QuoteStatus.DRAFT:
            raise QuoteInvalidTransitionError(
                "Line items can only be modified on draft quotes"
            )

        updates = {k: v for k, v in data.model_dump(exclude_none=True).items() if k in _LI_UPDATABLE_FIELDS}
        # Recompute total if qty/unit changed and total_price_cents not explicit
        if "total_price_cents" not in updates:
            qty = updates.get("quantity", current_li.quantity)
            unit = updates.get("unit_price_cents", current_li.unit_price_cents)
            if unit is not None:
                updates["total_price_cents"] = qty * unit

        if not updates:
            return current_li

        set_parts = []
        params: list = []
        for field, value in updates.items():
            set_parts.append(f"{field} = %s")
            params.append(value)
        set_parts.append("updated_at = %s")
        params.append(now_utc())
        params.append(li_id)

        row = self.postgres.execute_returning(
            f"UPDATE quote_line_items SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
            tuple(params),
        )[0]

        updated = QuoteLineItem.model_validate(row)
        changes = compute_changes(current_li.model_dump(mode="json"), updated.model_dump(mode="json"))
        if changes:
            self.audit.log_change(
                entity_type="quote_line_item",
                entity_id=li_id,
                action=AuditAction.UPDATE,
                changes=changes,
            )
        return updated

    def delete_line_item(self, li_id: UUID) -> bool:
        """Soft delete a quote line item."""
        current_li = self._get_line_item_by_id(li_id)
        if current_li is None:
            return False

        parent = self.get_by_id(current_li.quote_id)
        if parent is None or parent.status != QuoteStatus.DRAFT:
            raise QuoteInvalidTransitionError(
                "Line items can only be deleted on draft quotes"
            )

        now = now_utc()
        self.postgres.execute(
            "UPDATE quote_line_items SET deleted_at = %s, updated_at = %s WHERE id = %s",
            (now, now, li_id),
        )

        self.audit.log_change(
            entity_type="quote_line_item",
            entity_id=li_id,
            action=AuditAction.DELETE,
            changes={"deleted": current_li.model_dump(mode="json")},
        )
        return True

    def _get_line_item_by_id(self, li_id: UUID) -> QuoteLineItem | None:
        row = self.postgres.execute_single(
            "SELECT * FROM quote_line_items WHERE id = %s AND deleted_at IS NULL",
            (li_id,),
        )
        if row is None:
            return None
        return QuoteLineItem.model_validate(row)

    def summarize(self, quote: Quote) -> dict:
        """Compute total cents, item count, and total duration for a quote."""
        items = self.list_line_items(quote.id)
        total_cents = sum(li.total_price_cents or 0 for li in items)
        total_duration = sum(li.duration_minutes or 0 for li in items)
        return {
            "quote_id": str(quote.id),
            "item_count": len(items),
            "total_price_cents": total_cents,
            "total_duration_minutes": total_duration,
        }
