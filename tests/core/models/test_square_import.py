"""Square import DTO contracts."""

from decimal import Decimal
from contextlib import contextmanager
from uuid import UUID

from core.models.square_import import SquareImportBatchRequest
from core.services.square_import_service import SquareImportService
from utils.timezone import now_utc
from utils.workspace_context import workspace_context


def test_rich_square_batch_preserves_price_and_line_items():
    request = SquareImportBatchRequest(
        import_run_id=UUID("00000000-0000-0000-0000-000000000123"),
        sales=[
            {
                "square_id": "order-1",
                "square_customer_id": "customer-1",
                "occurred_at": "2025-03-04T17:05:00Z",
                "status": "COMPLETED",
                "currency": "USD",
                "subtotal_cents": 40000,
                "total_cents": 40000,
                "paid_cents": 40000,
                "matched_square_booking_id": "booking-1",
                "match_method": "conservative_customer_service_day",
                "lines": [
                    {
                        "square_uid": "line-1",
                        "square_catalog_object_id": "exterior",
                        "name": "Window Cleaning (Exterior)",
                        "quantity": "1",
                        "base_price_cents": 40000,
                        "total_price_cents": 40000,
                    }
                ],
            }
        ],
    )

    sale = request.sales[0]
    assert sale.total_cents == 40000
    assert sale.lines[0].name == "Window Cleaning (Exterior)"
    assert sale.lines[0].quantity == Decimal("1")


def test_addressless_square_booking_is_valid():
    request = SquareImportBatchRequest(
        import_run_id=UUID("00000000-0000-0000-0000-000000000123"),
        bookings=[
            {
                "square_id": "booking-virtual",
                "square_customer_id": "customer-1",
                "start_at": "2025-03-04T17:05:00Z",
                "duration_minutes": 30,
                "status": "completed",
                "closed_at": "2025-03-04T17:35:00Z",
                "location_type": "PHONE",
                "location_label": "Phone appointment",
                "location_address": None,
            }
        ],
    )

    assert request.bookings[0].location_type == "PHONE"
    assert request.bookings[0].location_address is None


class _ImportDb:
    def __init__(self):
        self.links = {}
        self.calls = []

    @contextmanager
    def transaction(self):
        yield

    def execute_single(self, query, params=None):
        if "FROM square_import_links" in query:
            target = self.links.get((params[0], params[1]))
            return {"target_id": target} if target else None
        return None

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if "INSERT INTO square_import_links" in query:
            self.links[(params[2], params[3])] = params[4]
        return []


class _Audit:
    def log_change(self, *args, **kwargs):
        return None


def test_import_batch_is_idempotent_by_square_source_id():
    service = SquareImportService(_ImportDb(), _Audit())
    request = SquareImportBatchRequest(
        import_run_id=UUID("00000000-0000-0000-0000-000000000123"),
        customers=[
            {
                "square_id": "customer-1",
                "first_name": "Taylor",
            }
        ],
        services=[
            {
                "square_id": "exterior",
                "name": "Window Cleaning (Exterior)",
                "price_cents": 40000,
            }
        ],
    )

    with workspace_context(
        UUID("00000000-0000-0000-0000-000000000001"),
        "America/Detroit",
    ):
        first = service.apply_batch(request)
        second = service.apply_batch(request)

    assert first.customers_created == 1
    assert first.services_created == 1
    assert second.existing_records == 2


def test_matched_ticket_lines_use_actual_square_order_prices():
    database = _ImportDb()
    service_id = UUID("00000000-0000-0000-0000-000000000010")
    ticket_id = UUID("00000000-0000-0000-0000-000000000020")
    run_id = UUID("00000000-0000-0000-0000-000000000123")
    database.links[("service", "exterior")] = service_id
    service = SquareImportService(database, _Audit())
    request = SquareImportBatchRequest(
        import_run_id=run_id,
        sales=[
            {
                "square_id": "order-1",
                "square_customer_id": "customer-1",
                "occurred_at": "2025-03-04T17:05:00Z",
                "status": "COMPLETED",
                "currency": "USD",
                "total_cents": 40000,
                "paid_cents": 40000,
                "matched_square_booking_id": "booking-1",
                "match_method": "conservative_customer_service_day",
                "lines": [
                    {
                        "square_uid": "line-1",
                        "square_catalog_object_id": "exterior",
                        "name": "Window Cleaning (Exterior)",
                        "quantity": "1",
                        "base_price_cents": 40000,
                        "total_price_cents": 40000,
                    }
                ],
            }
        ],
    )

    with workspace_context(
        UUID("00000000-0000-0000-0000-000000000001"),
        "America/Detroit",
    ):
        service._replace_ticket_lines_from_sale(ticket_id, request.sales[0], run_id)

    insert = next(
        call for call in database.calls if "INSERT INTO line_items" in call[0]
    )
    params = insert[1]
    assert params[2] == ticket_id
    assert params[3] == service_id
    assert params[4] == "Window Cleaning (Exterior)"
    assert params[6] == 40000
    assert params[7] == 40000
    assert "Square inferred financial match" in params[8]


class _HistoryDb:
    def execute(self, query, params=None):
        if "FROM square_sales" in query:
            return [
                {
                    "id": UUID("00000000-0000-0000-0000-000000000030"),
                    "workspace_id": UUID("00000000-0000-0000-0000-000000000001"),
                    "customer_id": UUID("00000000-0000-0000-0000-000000000002"),
                    "square_order_id": "order-1",
                    "occurred_at": now_utc(),
                    "status": "COMPLETED",
                    "currency": "USD",
                    "subtotal_cents": 40000,
                    "tax_cents": 0,
                    "discount_cents": 0,
                    "tip_cents": 0,
                    "service_charge_cents": 0,
                    "total_cents": 40000,
                    "paid_cents": 40000,
                    "refunded_cents": 0,
                    "receipt_url": "https://square.example/receipt",
                    "matched_ticket_id": UUID(
                        "00000000-0000-0000-0000-000000000020"
                    ),
                    "match_method": "conservative_customer_service_day",
                    "created_at": now_utc(),
                }
            ]
        if "FROM square_sale_lines" in query:
            return [
                {
                    "id": UUID("00000000-0000-0000-0000-000000000040"),
                    "square_uid": "line-1",
                    "square_catalog_object_id": "exterior",
                    "name": "Window Cleaning (Exterior)",
                    "quantity": Decimal("1"),
                    "base_price_cents": 40000,
                    "total_price_cents": 40000,
                    "total_tax_cents": 0,
                    "total_discount_cents": 0,
                    "total_service_charge_cents": 0,
                }
            ]
        raise AssertionError(query)


def test_customer_financial_history_returns_itemized_square_sales():
    service = SquareImportService(_HistoryDb(), _Audit())

    sales = service.list_sales_for_customer(
        UUID("00000000-0000-0000-0000-000000000002")
    )

    assert sales[0].total_cents == 40000
    assert sales[0].matched_ticket_id == UUID(
        "00000000-0000-0000-0000-000000000020"
    )
    assert sales[0].lines[0].name == "Window Cleaning (Exterior)"
    assert sales[0].lines[0].total_price_cents == 40000
