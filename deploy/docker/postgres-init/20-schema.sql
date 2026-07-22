\set ON_ERROR_STOP on
\i /opt/crm/schema.sql

CREATE TABLE schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (name)
VALUES ('20260721_structured_ticket_closeout.sql');
