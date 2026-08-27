"""Integration coverage for QuoteService — quote state machine, line items, summarize."""

from datetime import timedelta
from uuid import uuid4

import pytest

from core.exceptions import NotFoundError, QuoteInvalidTransitionError, QuoteNotFoundError
from core.models import (
    CustomerCreate,
    QuoteCreate,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteStatus,
    QuoteUpdate,
    TicketCreate,
)
from utils.timezone import now_utc


def _quote_data(customer_id):
    return QuoteCreate(customer_id=customer_id, title="Exterior windows", notes="Two-story")


class TestQuoteCreate:
    def test_creates_quote_in_draft(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Q", last_name="Buyer"))
        quote = quote_service.create(_quote_data(customer.id))
        assert quote.status == QuoteStatus.DRAFT
        assert quote.title == "Exterior windows"
        assert quote.customer_id == customer.id
        assert quote.deleted_at is None


class TestQuoteGet:
    def test_get_missing_returns_none(self, as_test_workspace, quote_service):
        assert quote_service.get_by_id(uuid4()) is None

    def test_get_returns_quote(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="G", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        assert quote_service.get_by_id(quote.id).id == quote.id


class TestQuoteUpdate:
    def test_updates_draft_fields(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="U", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        updated = quote_service.update(quote.id, QuoteUpdate(title="Revised title"))
        assert updated.title == "Revised title"

    def test_only_draft_is_editable(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="S", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        with pytest.raises(QuoteInvalidTransitionError, match="only draft quotes can be edited"):
            quote_service.update(quote.id, QuoteUpdate(title="Too Late"))

    def test_update_missing_raises(self, as_test_workspace, quote_service):
        with pytest.raises(QuoteNotFoundError, match="not found"):
            quote_service.update(uuid4(), QuoteUpdate(title="X"))


class TestQuoteTransitions:
    def test_sent_stamps_sent_at(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Send", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        sent = quote_service.transition(quote.id, "sent")
        assert sent.status == QuoteStatus.SENT
        assert sent.sent_at is not None

    def test_rejected_stamps_rejected_at(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Reject", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        rejected = quote_service.transition(quote.id, "rejected")
        assert rejected.status == QuoteStatus.REJECTED
        assert rejected.rejected_at is not None

    def test_expired_can_be_resent(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Expire", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        expired = quote_service.transition(quote.id, "expired")
        assert expired.status == QuoteStatus.EXPIRED
        resent = quote_service.transition(quote.id, "sent")
        assert resent.status == QuoteStatus.SENT

    def test_invalid_transition_rejected(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Inv", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))  # draft
        with pytest.raises(QuoteInvalidTransitionError, match="Invalid quote transition"):
            quote_service.transition(quote.id, "accepted")  # draft -> accepted illegal

    def test_transition_via_accept_directly_is_blocked(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Use", last_name="Accept"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        with pytest.raises(QuoteInvalidTransitionError, match="Use accept_quote"):
            quote_service.transition(quote.id, "accepted")

    def test_terminal_accepted_has_no_outgoing(self, as_test_workspace, quote_service, customer_service, ticket_service, address_service):
        customer = customer_service.create(CustomerCreate(first_name="Acc", last_name="Cust"))
        address = address_service.create(_address(customer.id))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        ticket = ticket_service.create(TicketCreate(
            customer_id=customer.id, address_id=address.id,
            scheduled_at=now_utc() + timedelta(days=1),
        ))
        quote_service.accept(quote.id, ticket.id)
        with pytest.raises(QuoteInvalidTransitionError, match="Invalid quote transition"):
            quote_service.transition(quote.id, "archived")


class TestQuoteAccept:
    def test_accept_requires_sent_status(self, as_test_workspace, quote_service, customer_service, ticket_service, address_service):
        customer = customer_service.create(CustomerCreate(first_name="Not", last_name="Sent"))
        address = address_service.create(_address(customer.id))
        quote = quote_service.create(_quote_data(customer.id))  # draft
        ticket = ticket_service.create(TicketCreate(
            customer_id=customer.id, address_id=address.id,
            scheduled_at=now_utc() + timedelta(days=1),
        ))
        with pytest.raises(QuoteInvalidTransitionError, match="must be 'sent' to accept"):
            quote_service.accept(quote.id, ticket.id)

    def test_accept_stamps_ticket_and_status(self, as_test_workspace, quote_service, customer_service, ticket_service, address_service):
        customer = customer_service.create(CustomerCreate(first_name="Accept", last_name="Cust"))
        address = address_service.create(_address(customer.id))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        ticket = ticket_service.create(TicketCreate(
            customer_id=customer.id, address_id=address.id,
            scheduled_at=now_utc() + timedelta(days=1),
        ))

        accepted = quote_service.accept(quote.id, ticket.id)
        assert accepted.status == QuoteStatus.ACCEPTED
        assert accepted.accepted_at is not None
        assert accepted.created_ticket_id == ticket.id


class TestQuoteLineItems:
    def test_create_line_item_on_draft(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="LI", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        li = quote_service.create_line_item(quote.id, QuoteLineItemCreate(
            description="Front windows", quantity=5, unit_price_cents=2000,
        ))
        assert li.total_price_cents == 10000  # computed by model validator
        assert li.quantity == 5

    def test_line_items_locked_when_not_draft(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Lock", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.transition(quote.id, "sent")
        with pytest.raises(QuoteInvalidTransitionError, match="only.*modified on draft quotes"):
            quote_service.create_line_item(quote.id, QuoteLineItemCreate(description="X"))

    def test_update_line_item_recomputes_total(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Recompute", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        li = quote_service.create_line_item(quote.id, QuoteLineItemCreate(
            description="Screens", quantity=2, unit_price_cents=500,
        ))
        # update quantity only; total should recompute to 3 * 500
        updated = quote_service.update_line_item(li.id, QuoteLineItemUpdate(quantity=3))
        assert updated.total_price_cents == 1500

    def test_delete_line_item(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Del", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        li = quote_service.create_line_item(quote.id, QuoteLineItemCreate(description="Gone"))
        assert quote_service.delete_line_item(li.id) is True
        assert quote_service.list_line_items(quote.id) == []

    def test_delete_line_item_missing_returns_false(self, as_test_workspace, quote_service):
        assert quote_service.delete_line_item(uuid4()) is False


class TestQuoteSummarize:
    def test_summarize_aggregates_totals(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Sum", last_name="Cust"))
        quote = quote_service.create(_quote_data(customer.id))
        quote_service.create_line_item(quote.id, QuoteLineItemCreate(
            description="A", quantity=1, unit_price_cents=10000, duration_minutes=60,
        ))
        quote_service.create_line_item(quote.id, QuoteLineItemCreate(
            description="B", quantity=2, unit_price_cents=5000, duration_minutes=30,
        ))
        summary = quote_service.summarize(quote)
        assert summary["item_count"] == 2
        assert summary["total_price_cents"] == 20000
        assert summary["total_duration_minutes"] == 90


class TestQuoteDelete:
    def test_delete_soft_deletes_quote_and_line_items(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="Del", last_name="Quote"))
        quote = quote_service.create(_quote_data(customer.id))
        li = quote_service.create_line_item(quote.id, QuoteLineItemCreate(description="Cascade"))
        assert quote_service.delete(quote.id) is True
        assert quote_service.get_by_id(quote.id) is None
        assert quote_service.list_line_items(quote.id) == []
        # line item row persists with deleted_at
        assert quote_service._get_line_item_by_id(li.id) is None

    def test_delete_missing_returns_false(self, as_test_workspace, quote_service):
        assert quote_service.delete(uuid4()) is False


class TestQuoteList:
    def test_list_filters_by_customer_and_paginates(self, as_test_workspace, quote_service, customer_service):
        a = customer_service.create(CustomerCreate(first_name="A", last_name="C"))
        b = customer_service.create(CustomerCreate(first_name="B", last_name="C"))
        qa = quote_service.create(_quote_data(a.id))
        qb = quote_service.create(_quote_data(b.id))
        # newest-first; customer A sees only qa
        page = quote_service.list_page(customer_id=a.id, status=None, limit=10, cursor=None)
        assert [q.id for q in page.quotes] == [qa.id]
        # full list newest-first
        page_all = quote_service.list_page(customer_id=None, status=None, limit=1, cursor=None)
        assert [q.id for q in page_all.quotes] == [qb.id]
        assert page_all.next_cursor is not None

    def test_list_filters_by_status(self, as_test_workspace, quote_service, customer_service):
        customer = customer_service.create(CustomerCreate(first_name="F", last_name="C"))
        draft = quote_service.create(_quote_data(customer.id))
        sent = quote_service.create(_quote_data(customer.id))
        quote_service.transition(sent.id, "sent")
        page = quote_service.list_page(customer_id=None, status="sent", limit=10, cursor=None)
        assert [q.id for q in page.quotes] == [sent.id]
        assert all(q.status == QuoteStatus.SENT for q in page.quotes)


class TestQuoteRLS:
    def test_workspace_isolation(self, as_test_workspace, test_workspace_id, test_workspace_b_id, quote_service, customer_service):
        from utils.workspace_context import workspace_context

        customer = customer_service.create(CustomerCreate(first_name="Private", last_name="Q"))
        quote = quote_service.create(_quote_data(customer.id))
        assert quote.workspace_id == test_workspace_id
        with workspace_context(test_workspace_b_id, "America/Chicago"):
            assert quote_service.get_by_id(quote.id) is None
            assert quote_service.list_page(customer_id=None, status=None, limit=10, cursor=None).quotes == []
        assert quote_service.get_by_id(quote.id) is not None


def _address(customer_id):
    from core.models import AddressCreate
    return AddressCreate(
        customer_id=customer_id, street="1 Quote Way", city="Austin", state="TX", zip="78701",
    )
