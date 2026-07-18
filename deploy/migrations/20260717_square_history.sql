-- Rich Square appointment and financial history for existing CRM databases.
\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE tickets ALTER COLUMN address_id DROP NOT NULL;
ALTER TABLE tickets ADD COLUMN location_type TEXT NOT NULL DEFAULT 'customer_address';
ALTER TABLE tickets ADD COLUMN location_label TEXT;
ALTER TABLE tickets ADD COLUMN location_address JSONB;
ALTER TABLE tickets ADD COLUMN source_system TEXT;
ALTER TABLE tickets ADD COLUMN source_record_id TEXT;
ALTER TABLE tickets ADD COLUMN financial_match_method TEXT;

CREATE TABLE square_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    customer_id UUID REFERENCES customers(id),
    square_order_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    currency CHAR(3) NOT NULL,
    subtotal_cents BIGINT NOT NULL DEFAULT 0,
    tax_cents BIGINT NOT NULL DEFAULT 0,
    discount_cents BIGINT NOT NULL DEFAULT 0,
    tip_cents BIGINT NOT NULL DEFAULT 0,
    service_charge_cents BIGINT NOT NULL DEFAULT 0,
    total_cents BIGINT NOT NULL DEFAULT 0,
    paid_cents BIGINT NOT NULL DEFAULT 0,
    refunded_cents BIGINT NOT NULL DEFAULT 0,
    receipt_url TEXT,
    matched_ticket_id UUID REFERENCES tickets(id),
    match_method TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, square_order_id)
);
CREATE INDEX idx_square_sales_customer
    ON square_sales(workspace_id, customer_id, occurred_at DESC);
ALTER TABLE square_sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY square_sales_isolation ON square_sales FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE square_sale_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    sale_id UUID NOT NULL REFERENCES square_sales(id) ON DELETE CASCADE,
    square_uid TEXT NOT NULL,
    square_catalog_object_id TEXT,
    name TEXT NOT NULL,
    quantity NUMERIC(18, 6) NOT NULL,
    base_price_cents BIGINT,
    total_price_cents BIGINT NOT NULL,
    total_tax_cents BIGINT NOT NULL DEFAULT 0,
    total_discount_cents BIGINT NOT NULL DEFAULT 0,
    total_service_charge_cents BIGINT NOT NULL DEFAULT 0,
    ordinal INT NOT NULL,
    UNIQUE(sale_id, square_uid)
);
CREATE INDEX idx_square_sale_lines_sale ON square_sale_lines(sale_id, ordinal);
ALTER TABLE square_sale_lines ENABLE ROW LEVEL SECURITY;
CREATE POLICY square_sale_lines_isolation ON square_sale_lines FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

CREATE TABLE square_import_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    square_id TEXT NOT NULL,
    target_id UUID NOT NULL,
    import_run_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, entity_type, square_id)
);
ALTER TABLE square_import_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY square_import_links_isolation ON square_import_links FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON square_sales, square_sale_lines, square_import_links
    TO crm_dbuser;

COMMIT;
