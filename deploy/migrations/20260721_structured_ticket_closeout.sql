-- Canonical exception-based closeout records, customer-history facts, plans, and actions.
\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE ticket_closeouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,

    actual_duration_minutes INT NOT NULL,
    work_reconciliation JSONB NOT NULL,
    customer_capture JSONB NOT NULL,
    next_service JSONB NOT NULL,
    technician_summary TEXT,

    final_subtotal_cents INT NOT NULL,
    invoice_ready BOOLEAN NOT NULL,
    future_ticket_id UUID REFERENCES tickets(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_closeouts_one_per_ticket UNIQUE (ticket_id),
    CONSTRAINT ticket_closeouts_positive_duration CHECK (actual_duration_minutes > 0),
    CONSTRAINT ticket_closeouts_nonnegative_subtotal CHECK (final_subtotal_cents >= 0)
);

CREATE INDEX idx_ticket_closeouts_workspace_created
    ON ticket_closeouts(workspace_id, created_at DESC);
CREATE INDEX idx_ticket_closeouts_future_ticket
    ON ticket_closeouts(future_ticket_id) WHERE future_ticket_id IS NOT NULL;

ALTER TABLE ticket_closeouts ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_closeouts_isolation ON ticket_closeouts FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE ticket_closeout_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_closeout_id UUID NOT NULL REFERENCES ticket_closeouts(id) ON DELETE CASCADE,
    line_item_id UUID NOT NULL REFERENCES line_items(id) ON DELETE RESTRICT,
    quoted_line_item JSONB,
    final_line_item JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_closeout_line_items_unique_line UNIQUE (ticket_closeout_id, line_item_id)
);

CREATE INDEX idx_ticket_closeout_line_items_closeout
    ON ticket_closeout_line_items(ticket_closeout_id);

ALTER TABLE ticket_closeout_line_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_closeout_line_items_isolation ON ticket_closeout_line_items FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE ticket_closeout_profile_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_closeout_id UUID NOT NULL REFERENCES ticket_closeouts(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address_id UUID REFERENCES addresses(id) ON DELETE SET NULL,
    update_type TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_label TEXT,
    payload JSONB NOT NULL,
    source TEXT NOT NULL,
    certainty TEXT NOT NULL,
    persistence TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_closeout_profile_updates_valid_subject CHECK (
        subject_type IN ('customer', 'contact', 'address', 'asset')
    ),
    CONSTRAINT ticket_closeout_profile_updates_valid_source CHECK (
        source IN ('customer_stated', 'technician_observed', 'technician_reported_customer_statement')
    ),
    CONSTRAINT ticket_closeout_profile_updates_valid_certainty CHECK (
        certainty IN ('confirmed', 'likely', 'unverified')
    ),
    CONSTRAINT ticket_closeout_profile_updates_valid_persistence CHECK (
        persistence IN ('durable', 'seasonal', 'temporary')
    )
);

CREATE INDEX idx_ticket_closeout_profile_updates_customer
    ON ticket_closeout_profile_updates(customer_id, created_at DESC);
CREATE INDEX idx_ticket_closeout_profile_updates_payload
    ON ticket_closeout_profile_updates USING GIN (payload);

ALTER TABLE ticket_closeout_profile_updates ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_closeout_profile_updates_isolation ON ticket_closeout_profile_updates FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE future_service_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_closeout_id UUID NOT NULL REFERENCES ticket_closeouts(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address_id UUID REFERENCES addresses(id) ON DELETE SET NULL,
    disposition TEXT NOT NULL,
    status TEXT NOT NULL,
    timing JSONB NOT NULL,
    planned_scope JSONB NOT NULL,
    planned_duration_minutes INT,
    pricing_status TEXT,
    scheduling_mode TEXT,
    routing_instruction TEXT,
    confirmation_channel TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT future_service_plans_valid_disposition CHECK (disposition IN ('book', 'remind')),
    CONSTRAINT future_service_plans_valid_status CHECK (status IN ('pending', 'reminder')),
    CONSTRAINT future_service_plans_valid_pricing CHECK (
        pricing_status IS NULL OR pricing_status IN ('set', 'catalog_default', 'set_later')
    ),
    CONSTRAINT future_service_plans_valid_scheduling CHECK (
        scheduling_mode IS NULL OR scheduling_mode IN ('date_window', 'route_flexible')
    ),
    CONSTRAINT future_service_plans_valid_confirmation CHECK (
        confirmation_channel IS NULL OR confirmation_channel IN ('email', 'text', 'phone', 'none')
    ),
    CONSTRAINT future_service_plans_positive_duration CHECK (
        planned_duration_minutes IS NULL OR planned_duration_minutes > 0
    )
);

CREATE TRIGGER future_service_plans_updated_at BEFORE UPDATE ON future_service_plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_future_service_plans_customer
    ON future_service_plans(customer_id, status, created_at DESC);

ALTER TABLE future_service_plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY future_service_plans_isolation ON future_service_plans FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE ticket_closeout_follow_up_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_closeout_id UUID NOT NULL REFERENCES ticket_closeouts(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address_id UUID REFERENCES addresses(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL,
    responsible_party TEXT NOT NULL,
    description TEXT NOT NULL,
    due_at TIMESTAMPTZ,
    channel TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_closeout_follow_up_actions_valid_type CHECK (action_type IN (
        'create_quote',
        'schedule_return_visit',
        'send_review_request',
        'send_referral_follow_up',
        'send_customer_message',
        'record_customer_callback',
        'track_customer_required_repair',
        'send_service_reminder',
        'send_confirmation'
    )),
    CONSTRAINT ticket_closeout_follow_up_actions_valid_party CHECK (
        responsible_party IN ('business', 'customer')
    ),
    CONSTRAINT ticket_closeout_follow_up_actions_valid_channel CHECK (
        channel IS NULL OR channel IN ('email', 'text', 'phone', 'none')
    ),
    CONSTRAINT ticket_closeout_follow_up_actions_valid_status CHECK (
        status IN ('open', 'completed', 'cancelled')
    )
);

CREATE TRIGGER ticket_closeout_follow_up_actions_updated_at BEFORE UPDATE ON ticket_closeout_follow_up_actions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_ticket_closeout_follow_up_actions_customer
    ON ticket_closeout_follow_up_actions(customer_id, status, due_at);

ALTER TABLE ticket_closeout_follow_up_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_closeout_follow_up_actions_isolation ON ticket_closeout_follow_up_actions FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ticket_closeouts,
       ticket_closeout_line_items,
       ticket_closeout_profile_updates,
       future_service_plans,
       ticket_closeout_follow_up_actions
    TO crm_dbuser;

COMMIT;
