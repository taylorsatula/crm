"""Tests for core domain models - custom validators only."""

import pytest
from pydantic import ValidationError
from uuid import uuid4


class TestCustomerCreate:
    """Tests for CustomerCreate custom validators."""

    def test_requires_at_least_one_name(self):
        """Rejects when no name fields provided."""
        from core.models import CustomerCreate

        with pytest.raises(ValidationError, match="(?i)at least one of"):
            CustomerCreate()

    def test_accepts_first_name_only(self):
        """Accepts just first_name."""
        from core.models import CustomerCreate

        c = CustomerCreate(first_name="Alice")
        assert c.first_name == "Alice"

    def test_accepts_business_name_only(self):
        """Accepts just business_name."""
        from core.models import CustomerCreate

        c = CustomerCreate(business_name="Acme Corp")
        assert c.business_name == "Acme Corp"


class TestServiceCreate:
    """Tests for ServiceCreate custom validators."""

    def test_fixed_requires_default_price(self):
        """Fixed pricing needs default_price_cents."""
        from core.models import ServiceCreate, PricingType

        with pytest.raises(ValidationError, match="default_price_cents"):
            ServiceCreate(name="Test", pricing_type=PricingType.FIXED)

    def test_fixed_accepts_with_price(self):
        """Fixed pricing works with default_price_cents."""
        from core.models import ServiceCreate, PricingType

        s = ServiceCreate(
            name="Test",
            pricing_type=PricingType.FIXED,
            default_price_cents=1500
        )
        assert s.default_price_cents == 1500

    def test_per_unit_requires_unit_price(self):
        """Per-unit pricing needs unit_price_cents."""
        from core.models import ServiceCreate, PricingType

        with pytest.raises(ValidationError, match="unit_price_cents"):
            ServiceCreate(name="Test", pricing_type=PricingType.PER_UNIT)

    def test_flexible_needs_no_price(self):
        """Flexible pricing doesn't require price upfront."""
        from core.models import ServiceCreate, PricingType

        s = ServiceCreate(name="Test", pricing_type=PricingType.FLEXIBLE)
        assert s.pricing_type == PricingType.FLEXIBLE


class TestLineItemCreate:
    """Tests for LineItemCreate custom validators."""

    def test_computes_total_from_quantity_and_unit(self):
        """Calculates total_price_cents if not provided."""
        from core.models import LineItemCreate

        li = LineItemCreate(
            service_id=uuid4(),
            quantity=5,
            unit_price_cents=1000
        )
        assert li.total_price_cents == 5000

    def test_uses_explicit_total_if_provided(self):
        """Uses provided total_price_cents over calculation."""
        from core.models import LineItemCreate

        li = LineItemCreate(
            service_id=uuid4(),
            quantity=5,
            unit_price_cents=1000,
            total_price_cents=4500  # Discounted
        )
        assert li.total_price_cents == 4500


class TestNoteCreate:
    """Tests for NoteCreate custom validators."""

    def test_requires_exactly_one_parent(self):
        """Must have either customer_id or ticket_id, not both or neither."""
        from core.models import NoteCreate

        # Neither
        with pytest.raises(ValidationError, match="Exactly one"):
            NoteCreate(content="Test")

        # Both
        with pytest.raises(ValidationError, match="Exactly one"):
            NoteCreate(content="Test", customer_id=uuid4(), ticket_id=uuid4())

    def test_accepts_customer_only(self):
        """Works with just customer_id."""
        from core.models import NoteCreate

        n = NoteCreate(content="Test", customer_id=uuid4())
        assert n.customer_id is not None
        assert n.ticket_id is None

    def test_accepts_ticket_only(self):
        """Works with just ticket_id."""
        from core.models import NoteCreate

        n = NoteCreate(content="Test", ticket_id=uuid4())
        assert n.ticket_id is not None
        assert n.customer_id is None
