-- Sales pipeline: quotes and quote line items.
\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE quotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

    status TEXT NOT NULL DEFAULT 'draft',

    title TEXT,
    notes TEXT,
    expires_at TIMESTAMPTZ,

    sent_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,

    created_ticket_id UUID REFERENCES tickets(id) ON DELETE SET NULL,
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT quotes_valid_status CHECK (
        status IN ('draft', 'sent', 'accepted', 'rejected', 'expired', 'archived')
    ),
    CONSTRAINT quotes_accepted_has_ticket CHECK (
        (status = 'accepted' AND created_ticket_id IS NOT NULL)
        OR status != 'accepted'
    )
);

CREATE TRIGGER quotes_updated_at BEFORE UPDATE ON quotes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_quotes_workspace ON quotes(workspace_id);
CREATE INDEX idx_quotes_customer ON quotes(customer_id);
CREATE INDEX idx_quotes_status ON quotes(workspace_id, status);
CREATE INDEX idx_quotes_lead ON quotes(lead_id);
CREATE INDEX idx_quotes_created ON quotes(workspace_id, created_at DESC);

ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;

CREATE POLICY quotes_isolation ON quotes FOR ALL
    USING (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
        AND deleted_at IS NULL
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    );

CREATE POLICY quotes_insert ON quotes FOR INSERT
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);


CREATE TABLE quote_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    quote_id UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    service_id UUID REFERENCES services(id) ON DELETE SET NULL,

    description TEXT,
    quantity INT NOT NULL DEFAULT 1,
    unit_price_cents INT,
    total_price_cents INT,
    duration_minutes INT,
    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT quote_line_items_positive_quantity CHECK (quantity > 0),
    CONSTRAINT quote_line_items_positive_prices CHECK (
        (unit_price_cents IS NULL OR unit_price_cents >= 0)
        AND (total_price_cents IS NULL OR total_price_cents >= 0)
    )
);

CREATE TRIGGER quote_line_items_updated_at BEFORE UPDATE ON quote_line_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_quote_line_items_quote ON quote_line_items(quote_id);
CREATE INDEX idx_quote_line_items_workspace ON quote_line_items(workspace_id);

ALTER TABLE quote_line_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY quote_line_items_isolation ON quote_line_items FOR ALL
    USING (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
        AND deleted_at IS NULL
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    );

CREATE POLICY quote_line_items_insert ON quote_line_items FOR INSERT
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

COMMIT;
