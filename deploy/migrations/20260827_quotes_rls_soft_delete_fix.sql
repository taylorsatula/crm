-- Fix quotes/quote_line_items RLS policies: drop the soft-delete predicate
-- from the workspace-isolation USING clause.
--
-- The original quotes_pipeline migration mixed business logic (deleted_at IS NULL)
-- into a FOR ALL security policy. That made UPDATE ... SET deleted_at violate the
-- policy, so QuoteService.delete() / delete_line_item() 500'd in production.
-- RLS is for workspace isolation only; soft deletes are filtered in the app layer
-- (QuoteService.get_by_id / list_page / list_line_items all WHERE deleted_at IS NULL).
-- This matches the customers/tickets/notes/line_items/services/leads pattern.
\set ON_ERROR_STOP on

BEGIN;

DROP POLICY IF EXISTS quotes_isolation ON quotes;
CREATE POLICY quotes_isolation ON quotes FOR ALL
    USING (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    );

DROP POLICY IF EXISTS quote_line_items_isolation ON quote_line_items;
CREATE POLICY quote_line_items_isolation ON quote_line_items FOR ALL
    USING (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    )
    WITH CHECK (
        workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
    );

COMMIT;
