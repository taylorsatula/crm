"""Tests for CatalogService (service catalog)."""

import pytest
from uuid import uuid4


@pytest.fixture
def catalog_service(db):
    """CatalogService with real DB."""
    from core.services.catalog_service import CatalogService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return CatalogService(db, audit)


class TestServiceCreate:
    """Tests for CatalogService.create."""

    def test_creates_fixed_price_service(self, db, as_test_user, catalog_service):
        """Creates service with fixed pricing."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Window Cleaning",
            pricing_type=PricingType.FIXED,
            default_price_cents=15000  # $150.00
        )

        service = catalog_service.create(data)

        assert service.name == "Window Cleaning"
        assert service.pricing_type == "fixed"
        assert service.default_price_cents == 15000

    def test_creates_per_unit_service(self, db, as_test_user, catalog_service):
        """Creates service with per-unit pricing."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Screen Cleaning",
            pricing_type=PricingType.PER_UNIT,
            unit_price_cents=500,  # $5.00 per unit
            unit_label="screen"
        )

        service = catalog_service.create(data)

        assert service.pricing_type == "per_unit"
        assert service.unit_price_cents == 500
        assert service.unit_label == "screen"

    def test_creates_flexible_service(self, db, as_test_user, catalog_service):
        """Creates service with flexible pricing (price set per appointment)."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Custom Job",
            pricing_type=PricingType.FLEXIBLE,
            description="Price determined on-site"
        )

        service = catalog_service.create(data)

        assert service.pricing_type == "flexible"
        assert service.default_price_cents is None
        assert service.unit_price_cents is None

    def test_flexible_can_have_optional_default(self, db, as_test_user, catalog_service):
        """Flexible services can have an optional default price as a starting point."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Gutter Cleaning",
            pricing_type=PricingType.FLEXIBLE,
            default_price_cents=10000,  # $100 default, can be adjusted
            description="Starting at $100, final price varies by condition"
        )

        service = catalog_service.create(data)

        assert service.pricing_type == "flexible"
        assert service.default_price_cents == 10000

    def test_sets_user_id_from_context(self, db, as_test_user, test_user_id, catalog_service):
        """user_id comes from context."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Test Service",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        )

        service = catalog_service.create(data)

        assert service.user_id == test_user_id

    def test_is_active_defaults_true(self, db, as_test_user, catalog_service):
        """New services are active by default."""
        from core.models import ServiceCreate, PricingType

        data = ServiceCreate(
            name="Active Service",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        )

        service = catalog_service.create(data)

        assert service.is_active is True


class TestServiceGetById:
    """Tests for CatalogService.get_by_id."""

    def test_returns_service_when_exists(self, db, as_test_user, catalog_service):
        """Get by ID returns service."""
        from core.models import ServiceCreate, PricingType

        created = catalog_service.create(ServiceCreate(
            name="Test",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        found = catalog_service.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id

    def test_returns_none_for_nonexistent(self, db, as_test_user, catalog_service):
        """Missing ID returns None."""
        result = catalog_service.get_by_id(uuid4())
        assert result is None


class TestServiceListActive:
    """Tests for CatalogService.list_active."""

    def test_returns_active_services(self, db, as_test_user, catalog_service):
        """List returns only active services."""
        from core.models import ServiceCreate, PricingType

        catalog_service.create(ServiceCreate(
            name="Active One",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))
        catalog_service.create(ServiceCreate(
            name="Active Two",
            pricing_type=PricingType.FIXED,
            default_price_cents=2000
        ))

        services = catalog_service.list_active()

        assert len(services) >= 2
        assert all(s.is_active for s in services)

    def test_excludes_inactive_services(self, db, as_test_user, catalog_service):
        """Inactive services not returned."""
        from core.models import ServiceCreate, ServiceUpdate, PricingType

        service = catalog_service.create(ServiceCreate(
            name="Will Deactivate",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        catalog_service.update(service.id, ServiceUpdate(is_active=False))

        services = catalog_service.list_active()

        assert not any(s.id == service.id for s in services)


class TestServiceUpdate:
    """Tests for CatalogService.update."""

    def test_updates_price(self, db, as_test_user, catalog_service):
        """Can update default_price_cents."""
        from core.models import ServiceCreate, ServiceUpdate, PricingType

        service = catalog_service.create(ServiceCreate(
            name="Updateable",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        updated = catalog_service.update(
            service.id,
            ServiceUpdate(default_price_cents=1500)
        )

        assert updated.default_price_cents == 1500

    def test_can_deactivate(self, db, as_test_user, catalog_service):
        """Can set is_active=False."""
        from core.models import ServiceCreate, ServiceUpdate, PricingType

        service = catalog_service.create(ServiceCreate(
            name="To Deactivate",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        updated = catalog_service.update(service.id, ServiceUpdate(is_active=False))

        assert updated.is_active is False


class TestServiceDelete:
    """Tests for CatalogService.delete."""

    def test_soft_deletes(self, db, db_admin, as_test_user, catalog_service):
        """Services are soft deleted."""
        from core.models import ServiceCreate, PricingType

        service = catalog_service.create(ServiceCreate(
            name="Delete Me",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        catalog_service.delete(service.id)

        # Row still exists with deleted_at set
        rows = db_admin.execute(
            "SELECT deleted_at FROM services WHERE id = %s",
            (service.id,)
        )
        assert len(rows) == 1
        assert rows[0]["deleted_at"] is not None

    def test_deleted_not_in_list(self, db, as_test_user, catalog_service):
        """Deleted services not returned by list_active."""
        from core.models import ServiceCreate, PricingType

        service = catalog_service.create(ServiceCreate(
            name="Will Delete",
            pricing_type=PricingType.FIXED,
            default_price_cents=1000
        ))

        catalog_service.delete(service.id)

        services = catalog_service.list_active()

        assert not any(s.id == service.id for s in services)
