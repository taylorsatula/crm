-- =============================================================================
-- CRM/Appointment System - Database Schema
-- =============================================================================
--
-- Target: PostgreSQL 16+
--
-- Production deployment:
--   1. Create database: CREATE DATABASE crm;
--   2. Connect as superuser: psql -U postgres -d crm -f schema.sql
--   3. Schema creates users, tables, RLS policies, and grants
--
-- Users created:
--   - crm_admin:  Schema owner, migration executor (password in Vault)
--   - crm_dbuser: Application user with RLS-enforced queries (password in Vault)
--
-- =============================================================================

-- -----------------------------------------------------------------------------
-- User Creation
-- -----------------------------------------------------------------------------
-- Create application users if they don't exist.
-- Passwords MUST be changed via Vault after initial deployment.
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    -- Create admin user for schema management
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'crm_admin') THEN
        CREATE USER crm_admin WITH PASSWORD 'CHANGE_IN_VAULT_IMMEDIATELY';
        RAISE NOTICE 'Created user: crm_admin';
    END IF;

    -- Create application user for queries
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'crm_dbuser') THEN
        CREATE USER crm_dbuser WITH PASSWORD 'CHANGE_IN_VAULT_IMMEDIATELY';
        RAISE NOTICE 'Created user: crm_dbuser';
    END IF;
END
$$;

-- Grant database-level privileges
GRANT ALL PRIVILEGES ON DATABASE crm TO crm_admin;
GRANT CONNECT ON DATABASE crm TO crm_dbuser;

-- Grant crm_admin ability to manage roles (needed for RLS)
ALTER USER crm_admin WITH CREATEROLE;

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- Fuzzy text search (trigram matching)

-- -----------------------------------------------------------------------------
-- Helper Functions
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SECTION 1: Authentication & Users
-- =============================================================================

-- -----------------------------------------------------------------------------
-- users
-- -----------------------------------------------------------------------------
-- Core user account. Initially user_id = business (single-user per business).
-- NO RLS - accessed during auth before context exists.
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    timezone TEXT DEFAULT 'America/Chicago',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    CONSTRAINT users_email_lowercase CHECK (email = lower(email))
);

CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_users_email ON users(email);


-- -----------------------------------------------------------------------------
-- magic_link_tokens
-- -----------------------------------------------------------------------------
-- Ephemeral auth tokens. Hard delete after use/expiry.
-- -----------------------------------------------------------------------------
CREATE TABLE magic_link_tokens (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT false,
    used_at TIMESTAMPTZ,
    CONSTRAINT magic_link_expires_after_created CHECK (expires_at > created_at)
);

CREATE INDEX idx_magic_link_tokens_expires ON magic_link_tokens(expires_at);
CREATE INDEX idx_magic_link_tokens_user ON magic_link_tokens(user_id);


-- -----------------------------------------------------------------------------
-- security_events
-- -----------------------------------------------------------------------------
-- Append-only auth audit log. NO RLS.
-- -----------------------------------------------------------------------------
CREATE TABLE security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    email TEXT,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ip_address INET,
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_security_events_created ON security_events(created_at);
CREATE INDEX idx_security_events_user ON security_events(user_id);
CREATE INDEX idx_security_events_type ON security_events(event_type);


-- =============================================================================
-- SECTION 2: Core Business Entities
-- =============================================================================

-- -----------------------------------------------------------------------------
-- customers
-- -----------------------------------------------------------------------------
-- People or businesses who receive services.
-- Soft delete. RLS filters to current user AND not deleted.
-- -----------------------------------------------------------------------------
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Name (person or business)
    first_name TEXT,
    last_name TEXT,
    business_name TEXT,

    -- Contact info
    email TEXT,
    phone TEXT,

    -- Primary address (convenience - full addresses in addresses table)
    address TEXT,

    -- External reference (for imports, legacy system IDs)
    reference_id TEXT,

    -- Referral tracking
    referred_by UUID REFERENCES customers(id) ON DELETE SET NULL,

    -- Notes
    notes TEXT,

    -- Preferences
    preferred_contact_method TEXT,  -- 'email', 'phone', 'text'
    preferred_time_of_day TEXT,     -- 'morning', 'afternoon', 'evening', 'any'

    -- Stripe integration (reference ID only - no sensitive data)
    stripe_customer_id TEXT,        -- Stripe customer ID (cus_xxx)

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    -- Must have at least a name
    CONSTRAINT customers_has_name CHECK (
        first_name IS NOT NULL OR last_name IS NOT NULL OR business_name IS NOT NULL
    )
);

CREATE TRIGGER customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Indexes
CREATE INDEX idx_customers_user ON customers(user_id);
CREATE INDEX idx_customers_referred_by ON customers(referred_by) WHERE referred_by IS NOT NULL;
CREATE INDEX idx_customers_reference_id ON customers(user_id, reference_id) WHERE reference_id IS NOT NULL;

-- Fuzzy search indexes (pg_trgm)
CREATE INDEX idx_customers_first_name_trgm ON customers USING GIN (first_name gin_trgm_ops);
CREATE INDEX idx_customers_last_name_trgm ON customers USING GIN (last_name gin_trgm_ops);
CREATE INDEX idx_customers_business_name_trgm ON customers USING GIN (business_name gin_trgm_ops);
CREATE INDEX idx_customers_email_trgm ON customers USING GIN (email gin_trgm_ops);
CREATE INDEX idx_customers_phone_trgm ON customers USING GIN (phone gin_trgm_ops);

-- RLS
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY customers_isolation ON customers FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY customers_insert ON customers FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- addresses
-- -----------------------------------------------------------------------------
-- Service locations for customers. One customer can have multiple.
-- Hard delete (CASCADE from customer).
-- -----------------------------------------------------------------------------
CREATE TABLE addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

    label TEXT,          -- "Home", "Office", "Rental Property"
    street TEXT NOT NULL,
    street2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    notes TEXT,          -- Gate codes, access instructions

    is_primary BOOLEAN NOT NULL DEFAULT false,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER addresses_updated_at BEFORE UPDATE ON addresses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_addresses_customer ON addresses(customer_id);
CREATE INDEX idx_addresses_user ON addresses(user_id);

-- RLS
ALTER TABLE addresses ENABLE ROW LEVEL SECURITY;

CREATE POLICY addresses_isolation ON addresses FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY addresses_insert ON addresses FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- services
-- -----------------------------------------------------------------------------
-- Service catalog. ONE SOURCE OF TRUTH for all service definitions.
-- Referenced by tickets, line_items, and recurring_templates.
-- Soft delete to preserve historical references.
-- -----------------------------------------------------------------------------
CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    description TEXT,

    -- Pricing: 'fixed', 'flexible', 'per_unit'
    -- All prices in cents (integer) to avoid floating point issues
    pricing_type TEXT NOT NULL,
    default_price_cents INT,          -- For fixed/flexible ($10.00 = 1000)
    unit_price_cents INT,             -- For per_unit
    unit_label TEXT,                  -- "screen", "window", "hour"

    is_active BOOLEAN NOT NULL DEFAULT true,
    display_order INT NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT services_valid_pricing CHECK (pricing_type IN ('fixed', 'flexible', 'per_unit')),
    CONSTRAINT services_fixed_needs_price CHECK (pricing_type != 'fixed' OR default_price_cents IS NOT NULL),
    CONSTRAINT services_per_unit_needs_price CHECK (pricing_type != 'per_unit' OR unit_price_cents IS NOT NULL)
);

CREATE TRIGGER services_updated_at BEFORE UPDATE ON services
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_services_user ON services(user_id);
CREATE INDEX idx_services_active ON services(user_id) WHERE is_active = true AND deleted_at IS NULL;

-- NO RLS: Services are a shared catalog, not user-scoped data.
-- Soft-delete filtering handled in application layer queries.


-- -----------------------------------------------------------------------------
-- tickets
-- -----------------------------------------------------------------------------
-- The core work entity. Ticket = Appointment = Job.
-- ALL invoices derive from tickets. No standalone invoices.
-- Mutable until closed, immutable after.
-- Soft delete.
-- -----------------------------------------------------------------------------
CREATE TABLE tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id),
    address_id UUID NOT NULL REFERENCES addresses(id),

    -- Status: scheduled → in_progress → completed, or cancelled
    status TEXT NOT NULL DEFAULT 'scheduled',

    -- Scheduling
    scheduled_at TIMESTAMPTZ NOT NULL,
    scheduled_duration_minutes INT,

    -- Confirmation flow
    confirmation_status TEXT DEFAULT 'pending',  -- pending, confirmed, declined, reschedule_requested
    confirmation_sent_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,

    -- Execution
    clock_in_at TIMESTAMPTZ,
    clock_out_at TIMESTAMPTZ,
    actual_duration_minutes INT,

    -- Close-out
    notes TEXT,
    closed_at TIMESTAMPTZ,

    -- Pricing
    is_price_estimated BOOLEAN NOT NULL DEFAULT false,  -- Shows "Estimated" in UI/emails, requires confirmation at close-out

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT tickets_valid_status CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
    CONSTRAINT tickets_valid_confirmation CHECK (confirmation_status IN ('pending', 'confirmed', 'declined', 'reschedule_requested')),
    CONSTRAINT tickets_clock_order CHECK (clock_out_at IS NULL OR clock_in_at IS NOT NULL),
    CONSTRAINT tickets_closed_status CHECK (closed_at IS NULL OR status IN ('completed', 'cancelled'))
);

CREATE TRIGGER tickets_updated_at BEFORE UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_tickets_user ON tickets(user_id);
CREATE INDEX idx_tickets_customer ON tickets(customer_id);
CREATE INDEX idx_tickets_scheduled ON tickets(user_id, scheduled_at);
CREATE INDEX idx_tickets_status ON tickets(user_id, status);
CREATE INDEX idx_tickets_date ON tickets(user_id, (scheduled_at::date));

-- RLS
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY tickets_isolation ON tickets FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY tickets_insert ON tickets FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- ticket_technicians
-- -----------------------------------------------------------------------------
-- Junction for ticket ↔ technician assignments.
-- Supports multiple technicians per ticket.
-- -----------------------------------------------------------------------------
CREATE TABLE ticket_technicians (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    technician_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'primary',  -- 'primary', 'assistant'
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ticket_id, technician_id)
);

CREATE INDEX idx_ticket_technicians_ticket ON ticket_technicians(ticket_id);
CREATE INDEX idx_ticket_technicians_technician ON ticket_technicians(technician_id);


-- -----------------------------------------------------------------------------
-- line_items
-- -----------------------------------------------------------------------------
-- Services performed on a ticket with pricing.
-- References services table (ONE SOURCE OF TRUTH).
-- Soft delete.
-- -----------------------------------------------------------------------------
CREATE TABLE line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES services(id),

    description TEXT,             -- Override service name if needed
    quantity INT NOT NULL DEFAULT 1,
    unit_price_cents INT,         -- Price per unit in cents
    total_price_cents INT NOT NULL, -- Total in cents ($10.00 = 1000)
    duration_minutes INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE TRIGGER line_items_updated_at BEFORE UPDATE ON line_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_line_items_ticket ON line_items(ticket_id);
CREATE INDEX idx_line_items_service ON line_items(service_id);

-- RLS
ALTER TABLE line_items ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY line_items_isolation ON line_items FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY line_items_insert ON line_items FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- invoices
-- -----------------------------------------------------------------------------
-- Billing documents. ALWAYS created from a ticket.
-- Even "standalone" invoices are tickets that convert instantly.
-- No separate invoice_line_items - uses ticket's line_items.
-- Soft delete.
-- -----------------------------------------------------------------------------
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id),
    ticket_id UUID NOT NULL REFERENCES tickets(id),  -- REQUIRED - always from ticket

    invoice_number TEXT NOT NULL,

    -- Status
    status TEXT NOT NULL DEFAULT 'draft',  -- draft, sent, partial, paid, void

    -- Amounts in cents (computed from ticket's line_items)
    subtotal_cents INT NOT NULL,      -- $10.00 = 1000
    tax_rate_bps INT DEFAULT 0,       -- Basis points: 1000 = 10%
    tax_amount_cents INT DEFAULT 0,
    total_amount_cents INT NOT NULL,
    amount_paid_cents INT DEFAULT 0,

    -- Dates
    issued_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    voided_at TIMESTAMPTZ,

    -- Stripe integration (reference IDs only - no sensitive data)
    stripe_checkout_session_id TEXT,   -- Checkout session (cs_xxx)
    stripe_payment_intent_id TEXT,     -- Payment intent (pi_xxx)

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT invoices_valid_status CHECK (status IN ('draft', 'sent', 'partial', 'paid', 'void')),
    CONSTRAINT invoices_unique_number UNIQUE (user_id, invoice_number)
);

CREATE TRIGGER invoices_updated_at BEFORE UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_invoices_user ON invoices(user_id);
CREATE INDEX idx_invoices_customer ON invoices(customer_id);
CREATE INDEX idx_invoices_ticket ON invoices(ticket_id);
CREATE INDEX idx_invoices_status ON invoices(user_id, status);

-- RLS
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY invoices_isolation ON invoices FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY invoices_insert ON invoices FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- =============================================================================
-- SECTION 3: Notes & Attributes
-- =============================================================================

-- -----------------------------------------------------------------------------
-- notes
-- -----------------------------------------------------------------------------
-- Free-form notes on customers or tickets.
-- LLM extracts structured attributes.
-- Soft delete.
-- -----------------------------------------------------------------------------
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    ticket_id UUID REFERENCES tickets(id) ON DELETE CASCADE,

    content TEXT NOT NULL,
    processed_at TIMESTAMPTZ,  -- When LLM extracted attributes

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT notes_has_parent CHECK (
        (customer_id IS NOT NULL AND ticket_id IS NULL) OR
        (customer_id IS NULL AND ticket_id IS NOT NULL)
    )
);

CREATE INDEX idx_notes_customer ON notes(customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX idx_notes_ticket ON notes(ticket_id) WHERE ticket_id IS NOT NULL;

-- RLS
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY notes_isolation ON notes FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY notes_insert ON notes FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- attributes
-- -----------------------------------------------------------------------------
-- Structured data on customers (from LLM or manual).
-- Key-value with JSONB values.
-- -----------------------------------------------------------------------------
CREATE TABLE attributes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

    key TEXT NOT NULL,
    value JSONB NOT NULL,

    source_type TEXT NOT NULL DEFAULT 'manual',  -- 'manual', 'llm_extracted'
    source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    confidence DECIMAL(3,2),  -- 0.00-1.00, for LLM-extracted only

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT attributes_unique_key UNIQUE (customer_id, key),
    CONSTRAINT attributes_valid_source CHECK (source_type IN ('manual', 'llm_extracted'))
);

CREATE TRIGGER attributes_updated_at BEFORE UPDATE ON attributes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_attributes_customer ON attributes(customer_id);
CREATE INDEX idx_attributes_key ON attributes(user_id, key);
CREATE INDEX idx_attributes_value ON attributes USING GIN (value);

-- RLS
ALTER TABLE attributes ENABLE ROW LEVEL SECURITY;

CREATE POLICY attributes_isolation ON attributes FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY attributes_insert ON attributes FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- =============================================================================
-- SECTION 4: Messaging
-- =============================================================================

-- -----------------------------------------------------------------------------
-- scheduled_messages
-- -----------------------------------------------------------------------------
-- Emails queued for future delivery.
-- -----------------------------------------------------------------------------
CREATE TABLE scheduled_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    ticket_id UUID REFERENCES tickets(id) ON DELETE SET NULL,

    message_type TEXT NOT NULL,  -- 'service_reminder', 'appointment_confirmation', 'appointment_reminder', 'custom'
    template_name TEXT,
    subject TEXT,
    body TEXT,

    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, sent, cancelled, failed

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT scheduled_messages_valid_status CHECK (status IN ('pending', 'sent', 'cancelled', 'failed', 'skipped')),
    CONSTRAINT scheduled_messages_valid_type CHECK (message_type IN ('service_reminder', 'appointment_confirmation', 'appointment_reminder', 'custom'))
);

CREATE INDEX idx_scheduled_messages_pending ON scheduled_messages(scheduled_for) WHERE status = 'pending';
CREATE INDEX idx_scheduled_messages_customer ON scheduled_messages(customer_id);

-- RLS
ALTER TABLE scheduled_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY scheduled_messages_isolation ON scheduled_messages FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY scheduled_messages_insert ON scheduled_messages FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- message_log
-- -----------------------------------------------------------------------------
-- Audit trail for all messages sent (success or failure).
-- Append-only. NO RLS - admin accessible.
-- -----------------------------------------------------------------------------
CREATE TABLE message_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    customer_id UUID,
    scheduled_message_id UUID REFERENCES scheduled_messages(id) ON DELETE SET NULL,

    -- Message details
    message_type TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT,

    -- Result
    status TEXT NOT NULL,  -- 'sent', 'failed', 'bounced', 'rejected'
    error_message TEXT,
    provider_message_id TEXT,  -- ID from email provider

    -- Timing
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);

CREATE INDEX idx_message_log_user ON message_log(user_id);
CREATE INDEX idx_message_log_customer ON message_log(customer_id);
CREATE INDEX idx_message_log_scheduled ON message_log(scheduled_message_id);
CREATE INDEX idx_message_log_status ON message_log(status);


-- =============================================================================
-- SECTION 5: Waitlist
-- =============================================================================

-- -----------------------------------------------------------------------------
-- waitlist
-- -----------------------------------------------------------------------------
-- Customers wanting earlier appointments.
-- References ANOTHER customer to enable "we'll be at Customer X's house nearby"
-- -----------------------------------------------------------------------------
CREATE TABLE waitlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

    -- "Notify me when you're near this other customer"
    -- This lets us surface: "You'll be at Jane Smith's house - Bob (waitlisted) lives nearby"
    near_customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    near_address_id UUID REFERENCES addresses(id) ON DELETE SET NULL,

    -- Preferences
    preferred_dates TEXT,
    preferred_time_of_day TEXT,  -- 'morning', 'afternoon', 'any'

    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notified_at TIMESTAMPTZ,

    CONSTRAINT waitlist_one_per_customer UNIQUE (customer_id)
);

CREATE TRIGGER waitlist_updated_at BEFORE UPDATE ON waitlist
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_waitlist_active ON waitlist(user_id) WHERE is_active = true;
CREATE INDEX idx_waitlist_near_customer ON waitlist(near_customer_id) WHERE near_customer_id IS NOT NULL;

-- RLS
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

CREATE POLICY waitlist_isolation ON waitlist FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY waitlist_insert ON waitlist FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- =============================================================================
-- SECTION 6: Leads
-- =============================================================================

-- -----------------------------------------------------------------------------
-- leads
-- -----------------------------------------------------------------------------
-- Potential customers captured from phone calls or inquiries.
-- Raw notes processed by LLM into structured data.
-- Soft delete. RLS filters to current user AND not deleted.
-- -----------------------------------------------------------------------------
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Status: new → contacted → qualified → converted|archived
    status TEXT NOT NULL DEFAULT 'new',

    -- Raw capture (what user types during call - source of truth)
    raw_notes TEXT NOT NULL,

    -- LLM-extracted structured data (nullable until processed)
    extracted_data JSONB,
    extracted_at TIMESTAMPTZ,

    -- Editable fields (from extraction or manual entry)
    name TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    service_interest TEXT,
    lead_source TEXT,        -- 'cold_call', 'referral', 'website', 'other'
    urgency TEXT,            -- 'low', 'medium', 'high'
    property_details TEXT,

    -- Reminder for follow-up (future CalDAV integration placeholder)
    reminder_at TIMESTAMPTZ,
    reminder_note TEXT,

    -- Conversion tracking
    converted_at TIMESTAMPTZ,
    converted_customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT leads_valid_status CHECK (status IN ('new', 'contacted', 'qualified', 'converted', 'archived')),
    CONSTRAINT leads_valid_urgency CHECK (urgency IS NULL OR urgency IN ('low', 'medium', 'high')),
    CONSTRAINT leads_valid_source CHECK (lead_source IS NULL OR lead_source IN ('cold_call', 'referral', 'website', 'other')),
    CONSTRAINT leads_converted_has_customer CHECK (
        (status = 'converted' AND converted_customer_id IS NOT NULL AND converted_at IS NOT NULL)
        OR status != 'converted'
    )
);

CREATE TRIGGER leads_updated_at BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Indexes
CREATE INDEX idx_leads_user ON leads(user_id);
CREATE INDEX idx_leads_status ON leads(user_id, status);
CREATE INDEX idx_leads_reminder ON leads(reminder_at) WHERE reminder_at IS NOT NULL AND status NOT IN ('converted', 'archived');
CREATE INDEX idx_leads_created ON leads(user_id, created_at);

-- Fuzzy search indexes (pg_trgm)
CREATE INDEX idx_leads_name_trgm ON leads USING GIN (name gin_trgm_ops);
CREATE INDEX idx_leads_phone_trgm ON leads USING GIN (phone gin_trgm_ops);
CREATE INDEX idx_leads_email_trgm ON leads USING GIN (email gin_trgm_ops);

-- RLS
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

-- RLS: User isolation only. Soft-delete filtering handled in application layer.
CREATE POLICY leads_isolation ON leads FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid)
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY leads_insert ON leads FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- =============================================================================
-- SECTION 7: Recurring Appointments
-- =============================================================================

-- -----------------------------------------------------------------------------
-- recurring_templates
-- -----------------------------------------------------------------------------
-- Templates for generating recurring appointments.
-- References services table - ONE SOURCE OF TRUTH.
-- -----------------------------------------------------------------------------
CREATE TABLE recurring_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address_id UUID NOT NULL REFERENCES addresses(id),

    -- Schedule
    interval_type TEXT NOT NULL,  -- 'days', 'weeks', 'months'
    interval_value INT NOT NULL,
    preferred_day_of_week INT,    -- 0=Sunday..6=Saturday (for weekly)
    preferred_time TIME,

    estimated_duration_minutes INT,
    notes TEXT,

    is_active BOOLEAN NOT NULL DEFAULT true,
    last_generated_at TIMESTAMPTZ,
    next_occurrence_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT recurring_valid_interval CHECK (interval_type IN ('days', 'weeks', 'months')),
    CONSTRAINT recurring_positive_interval CHECK (interval_value > 0),
    CONSTRAINT recurring_valid_dow CHECK (preferred_day_of_week IS NULL OR preferred_day_of_week BETWEEN 0 AND 6)
);

CREATE TRIGGER recurring_templates_updated_at BEFORE UPDATE ON recurring_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_recurring_templates_user ON recurring_templates(user_id);
CREATE INDEX idx_recurring_templates_next ON recurring_templates(next_occurrence_at) WHERE is_active = true;

-- RLS
ALTER TABLE recurring_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY recurring_templates_isolation ON recurring_templates FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY recurring_templates_insert ON recurring_templates FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- -----------------------------------------------------------------------------
-- recurring_template_services
-- -----------------------------------------------------------------------------
-- Services to include when generating tickets from template.
-- References services table - ONE SOURCE OF TRUTH.
-- NO service duplication - just quantity/price overrides if needed.
-- -----------------------------------------------------------------------------
CREATE TABLE recurring_template_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES recurring_templates(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,

    -- Overrides (NULL = use service defaults)
    quantity INT DEFAULT 1,
    custom_price DECIMAL(10,2),  -- NULL = use service default

    UNIQUE(template_id, service_id)
);

CREATE INDEX idx_recurring_template_services_template ON recurring_template_services(template_id);


-- =============================================================================
-- SECTION 8: Audit Trail
-- =============================================================================

-- -----------------------------------------------------------------------------
-- audit_log
-- -----------------------------------------------------------------------------
-- Universal change tracking. Append-only. NO RLS.
-- -----------------------------------------------------------------------------
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,  -- 'create', 'update', 'delete'
    changes JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT audit_valid_action CHECK (action IN ('create', 'update', 'delete'))
);

CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);


-- =============================================================================
-- SECTION 9: Model Authorization Queue
-- =============================================================================

-- -----------------------------------------------------------------------------
-- model_authorization_queue
-- -----------------------------------------------------------------------------
-- Queue for MCP actions requiring human authorization.
-- Pending requests show in web UI at /authorizations.
-- RLS filters to current user. Status tracked for polling.
-- -----------------------------------------------------------------------------
CREATE TABLE model_authorization_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- What action was requested
    domain TEXT NOT NULL,           -- 'contact', 'invoice', etc.
    action TEXT NOT NULL,           -- 'delete', 'void', etc.
    data JSONB NOT NULL,            -- Action parameters

    -- Why it requires authorization
    reason TEXT NOT NULL,           -- 'Customer has 15 tickets worth $4,500'

    -- Model's explanation
    model_reasoning TEXT,           -- Why model wants to do this

    -- Status: pending → authorized | denied | expired
    status TEXT NOT NULL DEFAULT 'pending',

    -- Human decision
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    decision_notes TEXT,            -- Human's note back to model

    -- For "Allow Always" - should we upgrade the permission?
    upgrade_permission BOOLEAN DEFAULT FALSE,

    -- Timestamps
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '24 hours'),

    CONSTRAINT auth_queue_valid_status CHECK (status IN ('pending', 'authorized', 'denied', 'expired')),
    CONSTRAINT auth_queue_decision_complete CHECK (
        (status = 'pending' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status IN ('authorized', 'denied') AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
        OR (status = 'expired')
    )
);

-- Indexes
CREATE INDEX idx_auth_queue_user_pending ON model_authorization_queue(user_id, status)
    WHERE status = 'pending';
CREATE INDEX idx_auth_queue_expires ON model_authorization_queue(expires_at)
    WHERE status = 'pending';

-- RLS
ALTER TABLE model_authorization_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY auth_queue_isolation ON model_authorization_queue FOR ALL
    USING (user_id = current_setting('app.current_user_id', true)::uuid);

CREATE POLICY auth_queue_insert ON model_authorization_queue FOR INSERT
    WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);


-- =============================================================================
-- SECTION 10: Input Sanitization Triggers
-- =============================================================================

-- -----------------------------------------------------------------------------
-- sanitize_sensitive_data()
-- -----------------------------------------------------------------------------
-- Defense-in-depth: Strip credit card numbers and SSNs from freeform text
-- fields. Last line of defense - backend middleware is primary sanitizer.
-- Uses [REDACTED] replacement so user can see something was removed.
-- -----------------------------------------------------------------------------

-- Generic function that sanitizes a given text value
CREATE OR REPLACE FUNCTION sanitize_text(input_text TEXT)
RETURNS TEXT AS $$
BEGIN
    IF input_text IS NULL THEN
        RETURN NULL;
    END IF;

    -- Credit card pattern: 13-19 digits with optional spaces/dashes
    -- Uses word boundaries to avoid matching inside longer numbers
    input_text := regexp_replace(
        input_text,
        '\m(\d[ -]*){13,19}\M',
        '[REDACTED]',
        'g'
    );

    -- SSN pattern: XXX-XX-XXXX or XXXXXXXXX
    input_text := regexp_replace(
        input_text,
        '\m\d{3}-?\d{2}-?\d{4}\M',
        '[REDACTED]',
        'g'
    );

    RETURN input_text;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- Trigger function for customers.notes
CREATE OR REPLACE FUNCTION sanitize_customers_notes()
RETURNS TRIGGER AS $$
BEGIN
    NEW.notes := sanitize_text(NEW.notes);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sanitize_customers_notes
    BEFORE INSERT OR UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION sanitize_customers_notes();


-- Trigger function for tickets.notes
CREATE OR REPLACE FUNCTION sanitize_tickets_notes()
RETURNS TRIGGER AS $$
BEGIN
    NEW.notes := sanitize_text(NEW.notes);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sanitize_tickets_notes
    BEFORE INSERT OR UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION sanitize_tickets_notes();


-- Trigger function for leads.raw_notes
CREATE OR REPLACE FUNCTION sanitize_leads_notes()
RETURNS TRIGGER AS $$
BEGIN
    NEW.raw_notes := sanitize_text(NEW.raw_notes);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sanitize_leads_notes
    BEFORE INSERT OR UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION sanitize_leads_notes();


-- Trigger function for notes.content
CREATE OR REPLACE FUNCTION sanitize_notes_content()
RETURNS TRIGGER AS $$
BEGIN
    NEW.content := sanitize_text(NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sanitize_notes_content
    BEFORE INSERT OR UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION sanitize_notes_content();


-- Trigger function for scheduled_messages.body
CREATE OR REPLACE FUNCTION sanitize_messages_body()
RETURNS TRIGGER AS $$
BEGIN
    NEW.body := sanitize_text(NEW.body);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sanitize_messages_body
    BEFORE INSERT OR UPDATE ON scheduled_messages
    FOR EACH ROW EXECUTE FUNCTION sanitize_messages_body();


-- =============================================================================
-- Permissions for crm_dbuser
-- =============================================================================
-- Grant application user access to all tables, sequences, and functions.
-- These grants allow RLS-enforced queries but not schema changes.
-- =============================================================================

-- Grant schema usage
GRANT USAGE ON SCHEMA public TO crm_dbuser;

-- Grant table permissions (RLS policies will filter data)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO crm_dbuser;

-- Grant sequence usage (for any serial columns, though we use UUIDs)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO crm_dbuser;

-- Grant function execution (gen_random_uuid, triggers, etc.)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO crm_dbuser;

-- Make grants apply to future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crm_dbuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO crm_dbuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO crm_dbuser;

-- =============================================================================
-- Deployment Verification
-- =============================================================================
-- Simple query to verify schema deployment.
-- Expected: 20 tables created.
-- =============================================================================

\echo ''
\echo '==================================================================='
\echo 'Schema deployment complete!'
\echo '==================================================================='
\echo ''

SELECT COUNT(*) as table_count
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

\echo ''
\echo 'Users created: crm_admin, crm_dbuser'
\echo 'IMPORTANT: Update passwords in Vault immediately!'
\echo ''
