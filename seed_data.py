"""Seed script to repopulate the CRM database with sample data."""

import sys
from datetime import datetime, timedelta, timezone, time as dtime
from uuid import UUID, uuid4

from psycopg import connect

ADMIN_URL = "postgresql://crm_admin:4efaqRp6nfYQ1xySofxbpyZvZw1XhJgwyGS2IQvJr5DlY_uM@127.0.0.1:5432/crm"
USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def now_utc():
    return datetime.now(timezone.utc)


def seed(conn):
    cur = conn.cursor()
    today = now_utc().date()
    now = now_utc()

    # Ensure test user exists
    cur.execute("""
        INSERT INTO users (id, email, created_at, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
    """, (USER_ID, "testuser@test.local", now, now))

    # Services catalog
    services = [
        ("Window Cleaning - Exterior", "fixed", 15000, None),
        ("Window Cleaning - Interior", "fixed", 12000, None),
        ("Window Cleaning - Full Service", "fixed", 25000, None),
        ("Screen Cleaning", "per_unit", None, 500),
        ("Gutter Cleaning", "per_unit", None, 800),
        ("Pressure Washing", "flexible", None, None),
        ("Gutter Guard Install", "per_unit", None, 1200),
        ("Solar Panel Cleaning", "fixed", 20000, None),
    ]
    service_ids = []
    for name, pricing_type, default_price, unit_price in services:
        sid = uuid4()
        service_ids.append(sid)
        cur.execute("""
            INSERT INTO services (id, user_id, name, pricing_type, default_price_cents, unit_price_cents, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)
        """, (sid, USER_ID, name, pricing_type, default_price, unit_price, now, now))

    # Alabama cities/zips for addresses
    locations = [
        ("Albertville", "AL", "35498"),
        ("Guntersville", "AL", "35976"),
        ("Scottsboro", "AL", "35768"),
        ("Florence", "AL", "35630"),
        ("Muscle Shoals", "AL", "35661"),
        ("Sheffield", "AL", "35660"),
        ("Tuscumbia", "AL", "35674"),
        ("Hanceville", "AL", "35077"),
        ("Arab", "AL", "35016"),
        ("Oneonta", "AL", "35121"),
    ]

    streets = [
        "445 Chestnut Road", "177 Sycamore Court", "54 Magnolia Drive",
        "900 Health Plaza", "156 Willow Lane", "256 Birch Lane",
        "119 Juniper Lane", "142 Oak Street", "200 Commerce Drive",
        "67 Spruce Way", "312 Poplar Street", "660 Industrial Park",
        "501 Beech Street", "198 Walnut Street", "42 Cedar Drive",
        "73 Pine Road", "880 Lakeview Drive", "178 Petal Lane",
        "364 Cypress Court", "777 River Road", "215 Wellness Way",
        "95 Valley View Road", "88 Hickory Lane", "290 Dogwood Way",
        "315 Elm Court", "89 Maple Avenue", "75 Oak Hill Road",
        "410 Financial District", "330 East Street", "500 Pinecrest Boulevard",
        "63 Redwood Avenue", "42 Park Avenue", "500 Main Street",
        "128 Market Street", "431 Ash Boulevard", "123 Test Lane",
    ]

    first_names = [
        "James", "Mary", "Robert", "Patricia", "John", "Jennifer",
        "Michael", "Linda", "David", "Elizabeth", "William", "Barbara",
        "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
        "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
        "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra",
        "Donald", "Ashley", "Steven", "Dorothy", "Paul", "Kimberly",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
        "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
        "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
        "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
        "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Walker", "Young", "Allen", "King", "Wright", "Scott",
    ]

    # Create customers and addresses
    customer_ids = []
    address_ids = []
    for i in range(36):
        cid = uuid4()
        customer_ids.append(cid)
        fn = first_names[i % len(first_names)]
        ln = last_names[i % len(last_names)]
        phone = f"(256) {100 + i}-{5000 + i * 7 % 10000:04d}"
        email = f"{fn.lower()}.{ln.lower()}@example.com"
        cur.execute("""
            INSERT INTO customers (id, user_id, first_name, last_name, phone, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (cid, USER_ID, fn, ln, phone, email, now, now))

        aid = uuid4()
        address_ids.append(aid)
        street = streets[i % len(streets)]
        city, state, zip_code = locations[i % len(locations)]
        label = "Home" if i % 3 != 2 else "Office"
        cur.execute("""
            INSERT INTO addresses (id, user_id, customer_id, label, street, city, state, zip, is_primary, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
        """, (aid, USER_ID, cid, label, street, city, state, zip_code, now, now))

    # Create tickets (mix of past, today, and upcoming)
    ticket_ids = []
    for i in range(24):
        tid = uuid4()
        ticket_ids.append(tid)
        cid = customer_ids[i % len(customer_ids)]
        aid = address_ids[i % len(address_ids)]

        if i < 6:
            # Completed tickets from past days
            sched_date = today - timedelta(days=i + 1)
            scheduled = datetime.combine(sched_date, dtime(8, 0), tzinfo=timezone.utc)
            status = "completed"
            clock_in = scheduled - timedelta(minutes=5)
            clock_out = scheduled + timedelta(minutes=45)
            actual_duration = 45
            closed_at = clock_out
        elif i < 10:
            # Today's tickets
            hour = 8 + i
            scheduled = datetime.combine(today, dtime(hour, 0), tzinfo=timezone.utc)
            status = "in_progress" if i == 6 else "scheduled"
            clock_in = scheduled - timedelta(minutes=5) if i == 6 else None
            clock_out = None
            actual_duration = None
            closed_at = None
        else:
            # Future tickets
            sched_date = today + timedelta(days=i - 9)
            scheduled = datetime.combine(sched_date, dtime(9, 0), tzinfo=timezone.utc)
            status = "scheduled"
            clock_in = None
            clock_out = None
            actual_duration = None
            closed_at = None

        cur.execute("""
            INSERT INTO tickets (id, user_id, customer_id, address_id, scheduled_at, scheduled_duration_minutes,
                status, confirmation_status, is_price_estimated, clock_in_at, clock_out_at,
                actual_duration_minutes, closed_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 60, %s, 'pending', false, %s, %s, %s, %s, %s, %s)
        """, (tid, USER_ID, cid, aid, scheduled, status,
              clock_in, clock_out, actual_duration, closed_at, now, now))

    # Add line items to some tickets
    for i in range(18):
        tid = ticket_ids[i]
        sid = service_ids[i % len(service_ids)]
        lid = uuid4()
        price = [15000, 12000, 25000][i % 3]
        cur.execute("""
            INSERT INTO line_items (id, user_id, ticket_id, service_id, quantity, unit_price_cents, total_price_cents, duration_minutes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 1, %s, %s, 45, %s, %s)
        """, (lid, USER_ID, tid, sid, price, price, now, now))

    # Create invoices for completed tickets
    for i in range(6):
        tid = ticket_ids[i]
        cid = customer_ids[i % len(customer_ids)]
        inv_id = uuid4()
        total = 15000
        cur.execute("""
            INSERT INTO invoices (id, user_id, customer_id, ticket_id, invoice_number, subtotal_cents,
                tax_rate_bps, tax_amount_cents, total_amount_cents, amount_paid_cents,
                status, issued_at, due_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s)
        """, (inv_id, USER_ID, cid, tid, f"INV-2026-{100 + i}", total, total, 0,
              "draft", now, now + timedelta(days=30), now, now))

    # Add some customer notes
    note_contents = [
        "Gate code is 1234",
        "Dog in yard - leash provided",
        "Side windows need extra attention",
        "Customer prefers morning visits",
        "Hard water spots on south-facing windows",
        "Second story has a ladder access point",
        "New construction - no furniture inside yet",
        "Ask about seasonal package deal",
        "Referred by existing customer",
        "Property manager handles scheduling",
    ]
    for i in range(10):
        cid = customer_ids[i]
        cur.execute("""
            INSERT INTO notes (id, user_id, customer_id, ticket_id, content, created_at)
            VALUES (%s, %s, %s, NULL, %s, %s)
        """, (uuid4(), USER_ID, cid, note_contents[i], now))

    conn.commit()
    print(f"Seeded: {len(customer_ids)} customers, {len(address_ids)} addresses, "
          f"{len(ticket_ids)} tickets, {len(services)} services, 6 invoices, 10 notes")


if __name__ == "__main__":
    with connect(ADMIN_URL) as conn:
        seed(conn)
    print("Done.")
