-- Structured ticket closeout record.
\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE ticket_closeouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,

    actual_duration_minutes INT NOT NULL,
    quoted_scope_status TEXT NOT NULL,
    result_status TEXT NOT NULL,
    customer_response TEXT NOT NULL,
    next_service_disposition TEXT NOT NULL,
    next_service_note TEXT,
    technician_summary TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_closeouts_one_per_ticket UNIQUE (ticket_id),
    CONSTRAINT ticket_closeouts_positive_duration CHECK (actual_duration_minutes > 0),
    CONSTRAINT ticket_closeouts_valid_scope CHECK (quoted_scope_status IN ('completed', 'partially_completed', 'not_completed')),
    CONSTRAINT ticket_closeouts_valid_result CHECK (result_status IN ('achieved', 'achieved_with_limitations', 'not_achieved', 'not_assessed')),
    CONSTRAINT ticket_closeouts_valid_response CHECK (customer_response IN ('positive_feedback', 'no_concern_stated', 'concern_stated', 'not_reviewed', 'contact_unavailable', 'unknown')),
    CONSTRAINT ticket_closeouts_valid_disposition CHECK (next_service_disposition IN ('book', 'remind', 'declined', 'undecided', 'not_applicable'))
);

CREATE INDEX idx_ticket_closeouts_workspace_created
    ON ticket_closeouts(workspace_id, created_at DESC);

ALTER TABLE ticket_closeouts ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_closeouts_isolation ON ticket_closeouts FOR ALL
    USING (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid)
    WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON ticket_closeouts TO crm_dbuser;

COMMIT;
